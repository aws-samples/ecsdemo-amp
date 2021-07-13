#!/usr/bin/env python3

# cdk: 1.25.0
from aws_cdk import (
    aws_ec2,
    aws_ecs,
    aws_ecs_patterns,
    aws_iam,
    aws_servicediscovery,
    core,
    aws_ssm,

)

from os import getenv


# Creating a construct that will populate the required objects created in the platform repo such as vpc, ecs cluster, and service discovery namespace
class BasePlatform(core.Construct):

    def __init__(self, scope: core.Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)
        self.environment_name = 'ecsworkshop'

        # The base platform stack is where the VPC was created, so all we need is the name to do a lookup and import it into this stack for use
        self.vpc = aws_ec2.Vpc.from_lookup(
            self, "VPC",
            vpc_name='{}-base/BaseVPC'.format(self.environment_name)
        )

        self.sd_namespace = aws_servicediscovery.PrivateDnsNamespace.from_private_dns_namespace_attributes(
            self, "SDNamespace",
            namespace_name=core.Fn.import_value('NSNAME'),
            namespace_arn=core.Fn.import_value('NSARN'),
            namespace_id=core.Fn.import_value('NSID')
        )

        self.ecs_cluster = aws_ecs.Cluster.from_cluster_attributes(
            self, "ECSCluster",
            cluster_name=core.Fn.import_value('ECSClusterName'),
            security_groups=[],
            vpc=self.vpc,
            default_cloud_map_namespace=self.sd_namespace
        )

        self.services_sec_grp = aws_ec2.SecurityGroup.from_security_group_id(
            self, "ServicesSecGrp",
            security_group_id=core.Fn.import_value('ServicesSecGrp')
        )


class AmpService(core.Stack):

    def __init__(self, scope: core.Stack, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        self.base_platform = BasePlatform(self, self.stack_name)

        file = open("ecs-fargate-adot-config.yaml")
        adot_config = file.read()
        file.close()

        exec_role = aws_iam.Role(
            self, 'AmpAppTaskExecutionRole-',
            assumed_by=aws_iam.ServicePrincipal('ecs-tasks.amazonaws.com'))
        exec_role.add_managed_policy(aws_iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AmazonECSTaskExecutionRolePolicy'))
        exec_role.add_managed_policy(aws_iam.ManagedPolicy.from_aws_managed_policy_name('AmazonSSMReadOnlyAccess'))

        self.fargate_task_def = aws_ecs.TaskDefinition(
            self, "aws-otel-FargateTask",
            compatibility=aws_ecs.Compatibility.EC2_AND_FARGATE,
            cpu='256',
            memory_mib='1024',
            execution_role=exec_role
        )

        self.container = self.fargate_task_def.add_container(
            "aws-otel-collector",
            image=aws_ecs.ContainerImage.from_registry("public.ecr.aws/aws-observability/aws-otel-collector:latest"),
            memory_reservation_mib=512,
            logging=aws_ecs.LogDriver.aws_logs(
                stream_prefix='/ecs/ecs-aws-otel-sidecar-collector-cdk'
            ),
            environment={
                "REGION": getenv('AWS_REGION'),
                "AOT_CONFIG_CONTENT": adot_config
            },
        )

        self.container = self.fargate_task_def.add_container(
            "prometheus-sample-app",
            image=aws_ecs.ContainerImage.from_registry("public.ecr.aws/pkashlik/prometheus-sample-app:latest"),
            memory_reservation_mib=256,
            logging=aws_ecs.LogDriver.aws_logs(
                stream_prefix='/ecs/prometheus-sample-app-cdk'
            ),
            environment={
                "REGION": getenv('AWS_REGION')
            },
        )

        self.fargate_service = aws_ecs.FargateService(
            self, "AmpFargateService",
            service_name='aws-otel-FargateService',
            task_definition=self.fargate_task_def,
            cluster=self.base_platform.ecs_cluster,
            security_group=self.base_platform.services_sec_grp,
            desired_count=1,
            cloud_map_options=aws_ecs.CloudMapOptions(
                cloud_map_namespace=self.base_platform.sd_namespace,
                name='aws-otel-FargateService'
            )
        )

        self.fargate_task_def.add_to_task_role_policy(
            aws_iam.PolicyStatement(
                actions=[ "logs:PutLogEvents","logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:DescribeLogStreams",
                "logs:DescribeLogGroups",
                "ssm:GetParameters",
                "aps:RemoteWrite"],
                resources=['*']
            )
        )

_env = core.Environment(account=getenv('AWS_ACCOUNT_ID'), region=getenv('AWS_DEFAULT_REGION'))
environment = "ecsworkshop"
stack_name = "{}-amp".format(environment)
app = core.App()
AmpService(app, stack_name, env=_env)
app.synth()