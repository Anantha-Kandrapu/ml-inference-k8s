import json
import pulumi
import pulumi_aws as aws
import logging
import os
from user_data import worker_user_data, master_user_data
from jenkins_setup import get_jenkins_user_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Generate key pair if it doesn't exist
if not os.path.exists("ml-inference.pub"):
    os.system("ssh-keygen -t rsa -b 2048 -f ml-inference -N ''")

# Read the public key
with open("ml-inference.pub", "r") as f:
    public_key = f.read().strip()

# Create key pair in AWS
key_pair = aws.ec2.KeyPair(
    "ml-infer-key",
    key_name="ml-infer-key",
    public_key=public_key,
    tags={"Name": "mlInference"},
)

# Create IAM role for EC2 instances
instance_role = aws.iam.Role(
    "instance-role",
    assume_role_policy=json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "ecr:GetAuthorizationToken",
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:GetRepositoryPolicy",
                        "ecr:DescribeRepositories",
                        "ecr:ListImages",
                        "ecr:DescribeImages",
                        "ecr:BatchGetImage",
                        "ecr:InitiateLayerUpload",
                        "ecr:UploadLayerPart",
                        "ecr:CompleteLayerUpload",
                        "ecr:PutImage",
                    ],
                    "Resource": "*",
                }
            ],
        }
    ),
)

instance_profile = aws.iam.InstanceProfile("instance-profile", role=instance_role.name)

# Create ECR repository
ecr_repo = aws.ecr.Repository(
    "ml-infer-ecr",
    name="ml-infer-ecr",
    image_scanning_configuration={"scanOnPush": True},
    tags={"Name": "ml-infer"},
)

# Export the repository URL
pulumi.export("ecr_repo_url", ecr_repo.repository_url)

# Config
EC2_CONFIG = {
    "master_instance_type": "c5.2xlarge",
    "worker_instance_type": "g4dn.xlarge",
    "worker_count": 3,
    "master_ami_id": "ami-0b8c6b923777519db",
    "worker_ami_id": "ami-081f526a977142913",
    "key_name": key_pair.key_name,
}

NETWORK_CONFIG = {
    "vpc_cidr": "10.0.0.0/16",
    "public_subnet_cidrs": ["10.0.1.0/24", "10.0.2.0/24"],
    "private_subnet_cidrs": ["10.0.3.0/24", "10.0.4.0/24"],
}

# Create VPC
logger.info("Creating VPC...")
vpc = aws.ec2.Vpc(
    "ml-inference-vpc",
    cidr_block=NETWORK_CONFIG["vpc_cidr"],
    enable_dns_hostnames=True,
    enable_dns_support=True,
    tags={"Name": "ml-infer-vpc"},
)

# Create Internet Gateway
igw = aws.ec2.InternetGateway("ml-infer-igw", vpc_id=vpc.id, tags={"Name": "ml-igw"})

# Create route table for public subnets
public_rt = aws.ec2.RouteTable(
    "public-rt",
    vpc_id=vpc.id,
    routes=[{"cidr_block": "0.0.0.0/0", "gateway_id": igw.id}],
    tags={"Name": "ml-public-rt"},
)

# Create public subnets
public_subnets = []
for i, cidr in enumerate(NETWORK_CONFIG["public_subnet_cidrs"]):
    subnet = aws.ec2.Subnet(
        f"public-subnet-{i}",
        vpc_id=vpc.id,
        cidr_block=cidr,
        map_public_ip_on_launch=True,
        availability_zone=f"us-west-2{chr(97 + i)}",
        tags={"Name": f"ml-public-subnet-{i}"},
    )
    public_subnets.append(subnet)

    # Associate each public subnet with the route table
    aws.ec2.RouteTableAssociation(
        f"public-rta-{i}", subnet_id=subnet.id, route_table_id=public_rt.id
    )


# Create private subnets
private_subnets = []
for i, cidr in enumerate(NETWORK_CONFIG["private_subnet_cidrs"]):
    subnet = aws.ec2.Subnet(
        f"private-subnet-{i}",
        vpc_id=vpc.id,
        cidr_block=cidr,
        availability_zone=f"us-west-2{chr(97 + i)}",
        tags={"Name": f"ml-private-subnet-{i}"},
    )
    private_subnets.append(subnet)

# Create security groups
logger.info("Creating security groups...")
master_sg = aws.ec2.SecurityGroup(
    "master-sg",
    vpc_id=vpc.id,
    description="Master node security group",
    ingress=[
        {
            "protocol": "tcp",
            "from_port": 10250,
            "to_port": 10250,
            "cidr_blocks": [NETWORK_CONFIG["vpc_cidr"]],
        },
        {
            "protocol": "tcp",
            "from_port": 2379,
            "to_port": 2380,
            "cidr_blocks": [NETWORK_CONFIG["vpc_cidr"]],
        },
        # SSH protocol is tcp, port 22
        {
            "protocol": "tcp",
            "from_port": 22,
            "to_port": 22,
            "cidr_blocks": ["0.0.0.0/0"],
        },
        # For the API server
        {
            "protocol": "tcp",
            "from_port": 8000,
            "to_port": 8000,
            "cidr_blocks": ["0.0.0.0/0"],
        },
        # For Kubernetes API server
        {
            "protocol": "tcp",
            "from_port": 6443,
            "to_port": 6443,
            "cidr_blocks": ["0.0.0.0/0"],
        },
    ],
    egress=[
        {"protocol": "-1", "from_port": 0, "to_port": 0, "cidr_blocks": ["0.0.0.0/0"]}
    ],
    tags={"Name": "ml-master-sg"},
)

worker_sg = aws.ec2.SecurityGroup(
    "worker-sg",
    vpc_id=vpc.id,
    description="Worker nodes security group",
    ingress=[
        {
            "protocol": "tcp",
            "from_port": 10250,
            "to_port": 10250,
            "cidr_blocks": [NETWORK_CONFIG["vpc_cidr"]],
        },
        {
            "protocol": "-1",
            "from_port": 0,
            "to_port": 0,
            "cidr_blocks": [NETWORK_CONFIG["vpc_cidr"]],
        },
        {
            "protocol": "tcp",
            "from_port": 22,
            "to_port": 22,
            "cidr_blocks": ["0.0.0.0/0"],
        },
        {
            "protocol": "tcp",
            "from_port": 8000,
            "to_port": 8000,
            "cidr_blocks": ["0.0.0.0/0"],
        },
    ],
    egress=[
        {"protocol": "-1", "from_port": 0, "to_port": 0, "cidr_blocks": ["0.0.0.0/0"]}
    ],
    tags={"Name": "ml-worker-sg"},
)
# Add after your existing EC2 instances setup
jenkins_sg = aws.ec2.SecurityGroup(
    "jenkins-sg",
    vpc_id=vpc.id,
    description="Jenkins security group",
    ingress=[
        {
            "protocol": "tcp",
            "from_port": 22,
            "to_port": 22,
            "cidr_blocks": ["0.0.0.0/0"],
        },
        {
            "protocol": "tcp",
            "from_port": 8080,
            "to_port": 8080,
            "cidr_blocks": ["0.0.0.0/0"],
        },
    ],
    egress=[
        {"protocol": "-1", "from_port": 0, "to_port": 0, "cidr_blocks": ["0.0.0.0/0"]}
    ],
)


jenkins_instance = aws.ec2.Instance(
    "jenkins",
    instance_type="c5.xlarge",
    ami=EC2_CONFIG["master_ami_id"],
    key_name=EC2_CONFIG["key_name"],
    subnet_id=public_subnets[0].id,
    vpc_security_group_ids=[jenkins_sg.id],
    iam_instance_profile=instance_profile.name,  # Use same profile or create specific
    user_data=get_jenkins_user_data(ecr_repo.repository_url),
    root_block_device={
        "volume_size": 100,
        "volume_type": "gp3",
        "iops": 3000,
    },
    tags={"Name": "jenkins"},
)

# Create master node
logger.info("Creating master node...")
master = aws.ec2.Instance(
    "ml-master",
    instance_type=EC2_CONFIG["master_instance_type"],
    ami=EC2_CONFIG["master_ami_id"],
    key_name=EC2_CONFIG["key_name"],
    iam_instance_profile=instance_profile.name,
    subnet_id=public_subnets[0].id,
    vpc_security_group_ids=[master_sg.id],
    metadata_options={
        "http_endpoint": "enabled",
        "http_tokens": "required",
        "http_put_response_hop_limit": 1,
    },
    root_block_device={
        "volume_size": 100,
        "volume_type": "gp3",
    },
    user_data=master_user_data,
    tags={"Name": "ml-master", "Role": "master"},
)

# After creating subnets and security groups, add:
pulumi.export("subnet_id", private_subnets[0].id)
pulumi.export("sg_id", worker_sg.id)

# Create worker node
logger.info("Creating worker node...")
try:
    worker = aws.ec2.Instance(
        "ml-worker",
        instance_type=EC2_CONFIG["worker_instance_type"],
        ami=EC2_CONFIG["worker_ami_id"],
        key_name=EC2_CONFIG["key_name"],
        subnet_id=private_subnets[0].id,
        vpc_security_group_ids=[worker_sg.id],
        iam_instance_profile=instance_profile.name,
        root_block_device={
            "volume_size": 100,
            "volume_type": "gp3",
        },
        metadata_options={
            "http_endpoint": "enabled",
            "http_tokens": "required",  # This enforces IMDSv2
            "http_put_response_hop_limit": 1,
        },
        user_data=worker_user_data,
        tags={"Name": "ml-worker"},
        opts=pulumi.ResourceOptions(depends_on=[master]),
    )
except Exception as e:
    logger.error(f"Failed to create worker: {str(e)}", exc_info=True)
    raise

# Export values
pulumi.export("vpc_id", vpc.id)
pulumi.export("master_ip", master.public_ip)
pulumi.export("worker_ip", worker.private_ip)
