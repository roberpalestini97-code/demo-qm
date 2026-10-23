import { execSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { CfnOutput, Duration, Fn, Stack, StackProps, Tags } from 'aws-cdk-lib';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as iot from 'aws-cdk-lib/aws-iot';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';

export interface QmDemosProps extends StackProps {
  instanceType: string;   // por ejemplo t3.small; tiene que figurar como free tier eligible
  repoUrl: string;
  branch: string;
  setId: string;          // set de fractura simulado; define el thing y los topics qm/{set}/...
  alertEmail?: string;    // si se pasa, crea un presupuesto de US$ 1 con aviso por mail
  ssmPrefix: string;      // Parameter Store: <prefix>/anthropic-api-key (la carga el operador) y <prefix>/consola-password
}

const APP_DIR = path.join(__dirname, '..', '..', 'telemetria_iot', 'app');
const LAMBDA_DEPS = '"psycopg[binary]==3.2.3"';

/**
 * Demos de QM en AWS.
 *
 *   data van (EC2) ─MQTT 8883, X.509─► IoT Core ─regla─► SQS (+ DLQ) ─► Lambda ingest ─► TimescaleDB (EC2)
 *
 * - EC2 con Docker: base, Grafana, agente, consola y Caddy. Sin SSH: el acceso es por SSM.
 * - VPC propia con una subred pública y sin NAT Gateway, que no es gratis. La Lambda solo habla con la base
 *   por IP privada; SQS la invoca desde afuera de la VPC, así que no necesita salida a internet.
 * - IP elástica, para que la URL <ip>.sslip.io y el certificado HTTPS no cambien al reiniciar.
 */
export class QmDemosStack extends Stack {
  constructor(scope: Construct, id: string, props: QmDemosProps) {
    super(scope, id, props);
    Tags.of(this).add('proyecto', 'qm-demos');
    const { setId, ssmPrefix } = props;
    const thingName = `datavan-${setId}`;

    // ── Red ────────────────────────────────────────────────────────────────────────────
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [{ name: 'publica', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 }],
    });

    const sg = new ec2.SecurityGroup(this, 'Web', { vpc, description: 'HTTP/HTTPS publico; Postgres solo desde la Lambda' });
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), 'HTTP (redirige a HTTPS y valida el certificado)');
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS');

    const lambdaSg = new ec2.SecurityGroup(this, 'IngestSg', { vpc, description: 'Lambda de ingesta' });
    sg.addIngressRule(lambdaSg, ec2.Port.tcp(5432), 'TimescaleDB desde la Lambda de ingesta');

    // ── IoT Core ───────────────────────────────────────────────────────────────────────
    const iotArn = (r: string) => `arn:aws:iot:${this.region}:${this.account}:${r}`;
    const thing = new iot.CfnThing(this, 'DataVan', { thingName });
    const policy = new iot.CfnPolicy(this, 'DataVanPolicy', {
      policyName: `${thingName}-policy`,
      policyDocument: {
        Version: '2012-10-17',
        Statement: [
          { Effect: 'Allow', Action: 'iot:Connect', Resource: [iotArn(`client/${thingName}`), iotArn('client/consola-api')] },
          { Effect: 'Allow', Action: ['iot:Publish', 'iot:RetainPublish'], Resource: [iotArn(`topic/qm/${setId}/*`)] },
          { Effect: 'Allow', Action: 'iot:Subscribe', Resource: [iotArn(`topicfilter/qm/${setId}/cmd`)] },
          { Effect: 'Allow', Action: 'iot:Receive', Resource: [iotArn(`topic/qm/${setId}/cmd`)] },
        ],
      },
    });

    // ── SQS ────────────────────────────────────────────────────────────────────────────
    const dlq = new sqs.Queue(this, 'TelemetriaDlq', { queueName: 'telemetria-dlq', retentionPeriod: Duration.days(14) });
    const queue = new sqs.Queue(this, 'Telemetria', {
      queueName: 'telemetria',
      visibilityTimeout: Duration.seconds(180), // 6 veces el timeout de la Lambda
      retentionPeriod: Duration.days(4),
      deadLetterQueue: { queue: dlq, maxReceiveCount: 5 },
    });

    const ruleRole = new iam.Role(this, 'ReglaRol', { assumedBy: new iam.ServicePrincipal('iot.amazonaws.com') });
    queue.grantSendMessages(ruleRole);
    new iot.CfnTopicRule(this, 'ReglaTelemetria', {
      ruleName: `qm_${setId.replace(/\W/g, '_')}_a_sqs`,
      topicRulePayload: {
        sql: `SELECT * FROM 'qm/${setId}/+' WHERE topic(3) = 'telemetria' OR topic(3) = 'eventos'`,
        awsIotSqlVersion: '2016-03-23',
        ruleDisabled: false,
        actions: [{ sqs: { queueUrl: queue.queueUrl, roleArn: ruleRole.roleArn, useBase64: false } }],
      },
    });

    // ── EC2 ────────────────────────────────────────────────────────────────────────────
    const role = new iam.Role(this, 'Rol', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore')],
    });
    // Para firmar el certificado del data van desde la EC2 (la clave privada no sale de la instancia).
    role.addToPolicy(new iam.PolicyStatement({
      actions: ['iot:CreateCertificateFromCsr', 'iot:DescribeEndpoint', 'iot:AttachPolicy', 'iot:AttachThingPrincipal'],
      resources: ['*'],
    }));
    // La API key de Claude la carga el operador como SecureString; la clave de la consola la guarda el setup.
    const param = (n: string) => `arn:aws:ssm:${this.region}:${this.account}:parameter${ssmPrefix}/${n}`;
    role.addToPolicy(new iam.PolicyStatement({
      actions: ['ssm:GetParameter'],
      resources: [param('anthropic-api-key'), param('consola-password')],
    }));
    role.addToPolicy(new iam.PolicyStatement({ actions: ['ssm:PutParameter'], resources: [param('consola-password')] }));

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
      `sudo -u ubuntu -i env PUBLIC_IP=${eip.attrPublicIp} AWS_REGION=${this.region} ` +
        `IOT_THING=${thingName} IOT_POLICY=${policy.policyName} SSM_PREFIX=${ssmPrefix} bash demo-qm/deploy/setup-ec2.sh`,
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
    instance.node.addDependency(thing, policy); // el setup los usa al arrancar
    new ec2.CfnEIPAssociation(this, 'IpAsociada', { allocationId: eip.attrAllocationId, instanceId: instance.instanceId });

    // ── Lambda de ingesta: el mismo qm/lambda_ingest.py que corre en local ──────────────
    const ingest = new lambda.Function(this, 'Ingest', {
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.X86_64,
      handler: 'qm.lambda_ingest.handler',
      code: lambda.Code.fromAsset(APP_DIR, {
        exclude: ['tests', '**/__pycache__', '**/*.pyc', 'Dockerfile', 'requirements.txt', 'qm/static'],
        bundling: {
          image: lambda.Runtime.PYTHON_3_12.bundlingImage,
          command: ['bash', '-c', `pip install ${LAMBDA_DEPS} -t /asset-output && cp -r qm /asset-output/`],
          // Sin Docker: pip baja las ruedas de Linux para Python 3.12 desde cualquier sistema.
          local: {
            tryBundle(outputDir: string) {
              try {
                execSync(`python -m pip install --quiet --platform manylinux2014_x86_64 --implementation cp ` +
                  `--python-version 3.12 --only-binary=:all: -t "${outputDir}" ${LAMBDA_DEPS}`, { stdio: 'inherit' });
                fs.cpSync(path.join(APP_DIR, 'qm'), path.join(outputDir, 'qm'), {
                  recursive: true, filter: (src) => !src.includes('__pycache__') && !src.includes('static'),
                });
                return true;
              } catch {
                return false;
              }
            },
          },
        },
      }),
      memorySize: 256,
      timeout: Duration.seconds(30),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      allowPublicSubnet: true,
      securityGroups: [lambdaSg],
      environment: {
        DATABASE_URL: `postgresql://qm:qm@${instance.instancePrivateIp}:5432/telemetria`,
      },
      logGroup: new logs.LogGroup(this, 'IngestLogs', { retention: logs.RetentionDays.ONE_WEEK }),
      description: 'IoT Core -> SQS -> TimescaleDB',
    });
    ingest.addEventSource(new SqsEventSource(queue, {
      batchSize: 50,
      maxBatchingWindow: Duration.seconds(5),
      reportBatchItemFailures: true,
      maxConcurrency: 2, // pocas conexiones a una base chica
    }));

    // ── Presupuesto ─────────────────────────────────────────────────────────────────────
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
    new CfnOutput(this, 'Url', { value: `https://${host}` });
    new CfnOutput(this, 'InstanceId', { value: instance.instanceId });
    new CfnOutput(this, 'PublicIp', { value: eip.attrPublicIp });
    new CfnOutput(this, 'Shell', { value: `aws ssm start-session --target ${instance.instanceId}` });
    new CfnOutput(this, 'Clave', {
      value: `aws ssm get-parameter --with-decryption --name ${ssmPrefix}/consola-password --query Parameter.Value --output text`,
      description: 'Contraseña de la consola y de Grafana (usuario qm)',
    });
    new CfnOutput(this, 'IotThing', { value: thingName });
    new CfnOutput(this, 'QueueUrl', { value: queue.queueUrl });
    new CfnOutput(this, 'DlqUrl', { value: dlq.queueUrl });
    new CfnOutput(this, 'IngestFunction', { value: ingest.functionName });
  }
}
