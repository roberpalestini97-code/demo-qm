#!/usr/bin/env node
import { App } from 'aws-cdk-lib';
import { QmDemosStack } from '../lib/qm-demos-stack';

const app = new App();
const ctx = (k: string, d?: string) => (app.node.tryGetContext(k) as string | undefined) ?? d;

new QmDemosStack(app, 'QmDemos', {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: ctx('region', 'us-east-1') },
  instanceType: ctx('instanceType', 't3.small')!,
  repoUrl: ctx('repoUrl', 'https://github.com/roberpalestini97-code/demo-qm.git')!,
  branch: ctx('branch', 'main')!,
  setId: ctx('setId', 'SET-01')!,
  alertEmail: ctx('alertEmail'),
  description: 'Demos de QM Equipment: EC2 con Docker, acceso por SSM',
});
