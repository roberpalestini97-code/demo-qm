import { CfnOutput, Fn, Stack, StackProps, Tags } from 'aws-cdk-lib';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface QmDemosProps extends StackProps {
  instanceType: string;   // por ejemplo t3.small; tiene que figurar como free tier eligible
  repoUrl: string;
  branch: string;
  alertEmail?: string;    // si se pasa, crea un presupuesto de US$ 1 con aviso por mail
}

/**
 * Una EC2 con todas las demos en Docker.
 * - Sin SSH: el acceso es por SSM (aws ssm start-session / send-command), con el puerto 22 cerrado.
 * - VPC propia con una sola subred pública y sin NAT Gateway, que no es gratis.
 * - IP elástica, para que la URL <ip>.sslip.io y el certificado HTTPS no cambien al reiniciar.
 */
export class QmDemosStack extends Stack {
  constructor(scope: Construct, id: string, props: QmDemosProps) {
    super(scope, id, props);
    Tags.of(this).add('proyecto', 'qm-demos');

    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [{ name: 'publica', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 }],
    });

    const sg = new ec2.SecurityGroup(this, 'Web', { vpc, description: 'Solo HTTP y HTTPS; sin SSH' });
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), 'HTTP (redirige a HTTPS y valida el certificado)');
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS');

    const role = new iam.Role(this, 'Rol', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore')],
    });

    const eip = new ec2.CfnEIP(this, 'Ip');

    const arm = /^[a-z]+\d+g/.test(props.instanceType); // t4g, m7g...
    const ami = ec2.MachineImage.fromSsmParameter(
      `/aws/service/canonical/ubuntu/server/24.04/stable/current/${arm ? 'arm64' : 'amd64'}/hvm/ebs-gp3/ami-id`,
      { os: ec2.OperatingSystemType.LINUX },
    );

    const userData = ec2.UserData.forLinux();
    userData.addCommands(
      'set -euxo pipefail',
      'apt-get update -y && apt-get install -y git',
      `sudo -u ubuntu -i bash -c 'git clone -b ${props.branch} ${props.repoUrl} demo-qm'`,
      `sudo -u ubuntu -i env PUBLIC_IP=${eip.attrPublicIp} bash demo-qm/deploy/setup-ec2.sh`,
    );

    const instance = new ec2.Instance(this, 'Servidor', {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      instanceType: new ec2.InstanceType(props.instanceType),
      machineImage: ami,
      securityGroup: sg,
      role,
      userData,
      requireImdsv2: true,
      blockDevices: [{
        deviceName: '/dev/sda1',
        volume: ec2.BlockDeviceVolume.ebs(30, { volumeType: ec2.EbsDeviceVolumeType.GP3, encrypted: true }),
      }],
    });

    new ec2.CfnEIPAssociation(this, 'IpAsociada', { allocationId: eip.attrAllocationId, instanceId: instance.instanceId });

    if (props.alertEmail) {
      new budgets.CfnBudget(this, 'Presupuesto', {
        budget: { budgetName: 'qm-demos-1usd', budgetType: 'COST', timeUnit: 'MONTHLY', budgetLimit: { amount: 1, unit: 'USD' } },
        notificationsWithSubscribers: [{
          notification: { notificationType: 'ACTUAL', comparisonOperator: 'GREATER_THAN', threshold: 1, thresholdType: 'PERCENTAGE' },
          subscribers: [{ subscriptionType: 'EMAIL', address: props.alertEmail }],
        }],
      });
    }

    const host = `${Fn.join('-', Fn.split('.', eip.attrPublicIp, 4))}.sslip.io`;
    new CfnOutput(this, 'InstanceId', { value: instance.instanceId });
    new CfnOutput(this, 'PublicIp', { value: eip.attrPublicIp });
    new CfnOutput(this, 'Url', { value: `https://${host}` });
    new CfnOutput(this, 'Shell', { value: `aws ssm start-session --target ${instance.instanceId}` });
  }
}
