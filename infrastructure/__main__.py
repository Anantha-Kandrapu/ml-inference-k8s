# __main__.py
import pulumi
import pulumi_aws as aws
import logging
import os

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
    "ml-inference",
    key_name="ml-inference",
    public_key=public_key,
    tags={"Name": "ml-inference"},
)


# Config
EC2_CONFIG = {
    "master_instance_type": "c5.2xlarge",
    "worker_instance_type": "g4dn.xlarge",
    "worker_count": 1,  # Start with 1 for testing
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
    "ml-vpc",
    cidr_block=NETWORK_CONFIG["vpc_cidr"],
    enable_dns_hostnames=True,
    enable_dns_support=True,
    tags={"Name": "ml-vpc"},
)

# Create Internet Gateway
igw = aws.ec2.InternetGateway("ml-igw", vpc_id=vpc.id, tags={"Name": "ml-igw"})

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
    tags={"Name": "ml-master-sg"},
)

worker_sg = aws.ec2.SecurityGroup(
    "worker-sg",
    vpc_id=vpc.id,
    description="Worker nodes security group",
    ingress=[
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


# Create master node
logger.info("Creating master node...")
master = aws.ec2.Instance(
    "ml-master",
    instance_type=EC2_CONFIG["master_instance_type"],
    ami=EC2_CONFIG["master_ami_id"],
    key_name=EC2_CONFIG["key_name"],
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
    user_data="""#!/bin/bash
        apt-get update
        apt-get install -y docker.io
        systemctl start docker
        systemctl enable docker
        usermod -a -G docker ubuntu
    """,
    tags={"Name": "ml-master"},
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
        root_block_device={
            "volume_size": 100,
            "volume_type": "gp3",
        },
        metadata_options={
            "http_endpoint": "enabled",
            "http_tokens": "required",  # This enforces IMDSv2
            "http_put_response_hop_limit": 1,
        },
        user_data="""#!/bin/bash
            apt-get update
            apt-get install -y docker.io
            systemctl start docker
            systemctl enable docker
            usermod -a -G docker ubuntu
        """,
        tags={"Name": "ml-worker"},
    )
except Exception as e:
    logger.error(f"Failed to create worker: {str(e)}", exc_info=True)
    raise

# Export values
pulumi.export("vpc_id", vpc.id)
pulumi.export("master_ip", master.public_ip)
pulumi.export("worker_ip", worker.private_ip)


# Create ECR repository
ecr_repo = aws.ecr.Repository("ml-inference",
    name="ml-inference",
    image_scanning_configuration={
        "scanOnPush": True
    },
    tags={
        "Name": "ml-inference"
    })

# Export the repository URL
pulumi.export('ecr_repo_url', ecr_repo.repository_url)
