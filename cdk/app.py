import aws_cdk as cdk

from aws_cdk import (
    App,
    Aspects,
    Aws,
    Environment,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecr_assets as ecr_a,
    aws_iam as iam,
    aws_logs as logs,
)

from os import getenv


class AmpService(cdk.Stack):

    def __init__(self, scope: cdk.Stack, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        self.vpc = ec2.Vpc(self, "VPC")

        self.ecs_cluster = ecs.Cluster(self, "DemoCluster", vpc=self.vpc)

        with open("ecs-fargate-adot-config.yaml", 'r') as f:
            adot_config = f.read()

        self.fargate_task_def = ecs.TaskDefinition(
            self, "aws-otel-FargateTask",
            compatibility=ecs.Compatibility.EC2_AND_FARGATE,
            cpu='256',
            memory_mib='1024'
        )

        self.adot_log_grp = logs.LogGroup(
            self, "AdotLogGroup",
            removal_policy=cdk.RemovalPolicy.DESTROY
        )

        self.app_log_grp = logs.LogGroup(
            self, "AppLogGroup",
            removal_policy=cdk.RemovalPolicy.DESTROY
        )

        self.otel_container = self.fargate_task_def.add_container(
            "aws-otel-collector",
            image=ecs.ContainerImage.from_registry("public.ecr.aws/aws-observability/aws-otel-collector:latest"),
            memory_reservation_mib=512,
            logging=ecs.LogDriver.aws_logs(
                stream_prefix='/ecs/ecs-aws-otel-sidecar-collector-cdk',
                log_group=self.adot_log_grp
            ),
            environment={
                "REGION": getenv('AWS_REGION'),
                "AOT_CONFIG_CONTENT": adot_config
            },
        )

        self.prom_container = self.fargate_task_def.add_container(
            "prometheus-sample-app",
            image=ecs.ContainerImage.from_docker_image_asset(
                asset=ecr_a.DockerImageAsset(
                    self, "PromAppImage",
                    directory='../prometheus'
                )
            ),
            memory_reservation_mib=256,
            logging=ecs.LogDriver.aws_logs(
                stream_prefix='/ecs/prometheus-sample-app-cdk',
                log_group=self.app_log_grp
            ),
            environment={
                "REGION": getenv('AWS_REGION')
            },
        )

        self.fargate_service = ecs.FargateService(
            self, "AmpFargateService",
            service_name='aws-otel-FargateService',
            task_definition=self.fargate_task_def,
            cluster=self.ecs_cluster,
            desired_count=1,
        )

        self.fargate_task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:PutLogEvents",
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:DescribeLogStreams",
                    "logs:DescribeLogGroups",
                    "ssm:GetParameters",
                    "aps:RemoteWrite"
                ],
                resources=['*']
            )
        )


_env = cdk.Environment(account=getenv('AWS_ACCOUNT_ID'), region=getenv('AWS_DEFAULT_REGION'))
app = cdk.App()
AmpService(app, "ecsworkshopAmpDemo", env=_env)
app.synth()
