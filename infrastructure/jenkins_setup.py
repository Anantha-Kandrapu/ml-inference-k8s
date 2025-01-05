def get_jenkins_user_data(
    ecr_url,
    github_repo="https://github.com/Anantha-Kandrapu/ml-inference-k8s",
    branch="pureDev",
):

    job_config = f"""<?xml version='1.1' encoding='UTF-8'?>
    <flow-definition plugin="workflow-job">
      <description>ML Inference Pipeline</description>
      <keepDependencies>false</keepDependencies>
      <definition class="org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition">
        <scm class="hudson.plugins.git.GitSCM">
          <configVersion>2</configVersion>
          <userRemoteConfigs>
            <hudson.plugins.git.UserRemoteConfig>
              <url>{github_repo}</url>
            </hudson.plugins.git.UserRemoteConfig>
          </userRemoteConfigs>
          <branches>
            <hudson.plugins.git.BranchSpec>
              <name>*/{branch}</name>
            </hudson.plugins.git.BranchSpec>
          </branches>
        </scm>
        <scriptPath>infrastructure/Jenkinsfile</scriptPath>
        <lightweight>true</lightweight>
      </definition>
    </flow-definition>"""

    # Define required plugins
    JENKINS_PLUGINS = [
        "workflow-aggregator",  # Pipeline plugin
        "git",  # Git integration
        "github",  # GitHub integration
        "docker-workflow",  # Docker Pipeline integration
        "pipeline-aws",  # AWS Pipeline steps
        "credentials-binding",  # Credentials management
        "amazon-ecr",  # AWS ECR integration
        "docker-plugin",  # Docker integration
        "aws-credentials",  # AWS credentials
        "pipeline-stage-view",  # Pipeline visualization
        "blueocean",  # Modern UI
        "configuration-as-code",  # JCasC plugin
        "job-dsl",  # Job DSL plugin
        "authorize-project",  # Security plugin
        "cloudbees-folder",  # Folder organization
        "timestamper",  # Add timestamps to logs
        "workflow-basic-steps",  # Basic Pipeline steps
        "workflow-cps",  # Pipeline groovy integration
        "workflow-job",  # Pipeline job integration
        "workflow-step-api",  # Pipeline step API
        "workflow-support",  # Pipeline support
        "antisamy-markup-formatter",  # HTML sanitizer
        "build-timeout",  # Build timeout
        "credentials",  # Credentials plugin
        "gradle",  # Gradle integration
        "ldap",  # LDAP integration
        "matrix-auth",  # Matrix authorization
        "pam-auth",  # PAM authentication
        "ssh-slaves",  # SSH build agents
        "email-ext",  # Email integration
        "mailer",  # Mail utility
        "ws-cleanup",  # Workspace cleanup
    ]

    return f"""#!/bin/bash
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
echo "Starting Jenkins setup..."

# System updates
apt-get update
apt-get install -y apt-transport-https ca-certificates curl software-properties-common gnupg

# Install Java 17
apt-get install -y openjdk-17-jdk

# Add Jenkins repository key
curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io-2023.key | sudo tee \
  /usr/share/keyrings/jenkins-keyring.asc > /dev/null

# Add Jenkins repository
echo deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc] \
  https://pkg.jenkins.io/debian-stable binary/ | sudo tee \
  /etc/apt/sources.list.d/jenkins.list > /dev/null

# Install Jenkins
apt-get update
apt-get install -y jenkins

# Create required directories
mkdir -p /var/lib/jenkins
mkdir -p /var/cache/jenkins
mkdir -p /var/log/jenkins

# Set correct permissions
chown -R jenkins:jenkins /var/lib/jenkins
chown -R jenkins:jenkins /var/cache/jenkins
chown -R jenkins:jenkins /var/log/jenkins
chmod 755 /var/lib/jenkins
chmod 755 /var/cache/jenkins
chmod 755 /var/log/jenkins

# Configure Jenkins service
cat <<EOF > /lib/systemd/system/jenkins.service
[Unit]
Description=Jenkins Continuous Integration Server
Requires=network.target
After=network.target

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/java -Djava.awt.headless=true -jar /usr/share/java/jenkins.war --webroot=/var/cache/jenkins/war --httpPort=8080
Restart=on-failure
User=jenkins
Group=jenkins
Environment="JENKINS_HOME=/var/lib/jenkins"
Environment="JENKINS_PORT=8080"
Environment="JAVA_OPTS=-Djava.awt.headless=true -Xmx2048m -Xms1024m"

[Install]
WantedBy=multi-user.target
EOF

# Configure Jenkins defaults
cat <<EOF > /etc/default/jenkins
JENKINS_HOME=/var/lib/jenkins
JENKINS_USER=jenkins
JENKINS_JAVA_OPTIONS="-Djava.awt.headless=true -Xmx2048m -Xms1024m"
JENKINS_PORT=8080
EOF

# Install Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io

# Configure Docker
mkdir -p /etc/docker
cat <<EOF > /etc/docker/daemon.json
{docker_config}
EOF

# Load required kernel modules
modprobe overlay
modprobe br_netfilter

# Configure kernel parameters
cat <<EOF > /etc/sysctl.d/99-kubernetes-cri.conf
net.bridge.bridge-nf-call-iptables  = 1
net.ipv4.ip_forward                 = 1
net.bridge.bridge-nf-call-ip6tables = 1
EOF
sysctl --system

# Add jenkins user to docker group
usermod -aG docker jenkins
chmod 666 /var/run/docker.sock

# Install AWS CLI
apt-get install -y awscli

# Start services
systemctl daemon-reload
systemctl enable docker
systemctl start docker
systemctl enable jenkins
systemctl start jenkins

# Wait for Jenkins to start
echo "Waiting for Jenkins to start..."
until curl -s -I http://localhost:8080/login | grep "200 OK"; do
    sleep 10
done

# Get Jenkins initial admin password
JENKINS_PASS=$(sudo cat /var/lib/jenkins/secrets/initialAdminPassword)
echo "Jenkins initial admin password: $JENKINS_PASS"

# Download Jenkins CLI
wget http://localhost:8080/jnlpJars/jenkins-cli.jar -O /usr/local/bin/jenkins-cli.jar
chmod +x /usr/local/bin/jenkins-cli.jar

# Install plugins with retry mechanism
max_retries=3
retry_count=0
while [ $retry_count -lt $max_retries ]; do
    if java -jar /usr/local/bin/jenkins-cli.jar -s http://localhost:8080/ -auth admin:$JENKINS_PASS install-plugin {' '.join(JENKINS_PLUGINS)} -deploy; then
        echo "Plugin installation successful"
        break
    else
        echo "Plugin installation failed, retrying..."
        retry_count=$((retry_count + 1))
        sleep 30
    fi
done

# Create Jenkins configuration scripts
mkdir -p /var/lib/jenkins/init.groovy.d
{groovy_setup}

# Create job configuration
mkdir -p /var/lib/jenkins/jobs/ml-inference
cat <<EOF > /var/lib/jenkins/jobs/ml-inference/config.xml
{job_config}
EOF

# Set permissions
chown -R jenkins:jenkins /var/lib/jenkins
chmod -R 755 /var/lib/jenkins

# Execute Groovy scripts
java -jar /usr/local/bin/jenkins-cli.jar -s http://localhost:8080/ -auth admin:$JENKINS_PASS groovy /var/lib/jenkins/init.groovy.d/set-env.groovy

# Restart Jenkins to apply changes
java -jar /usr/local/bin/jenkins-cli.jar -s http://localhost:8080/ -auth admin:$JENKINS_PASS safe-restart

echo "Jenkins setup completed. Initial admin password: $JENKINS_PASS"
"""


groovy_script = """
import jenkins.model.*
import hudson.slaves.EnvironmentVariablesNodeProperty

def jenkins = Jenkins.getInstance()
def globalNodeProperties = jenkins.getGlobalNodeProperties()

// Remove existing environment variables
globalNodeProperties.removeAll({ it instanceof EnvironmentVariablesNodeProperty })

// Create new environment variables
def envVarsNodeProperty = new EnvironmentVariablesNodeProperty()
def envVars = envVarsNodeProperty.getEnvVars()

// Add our environment variables
envVars.put("ECR_URL", "${ecr_url}")
envVars.put("GITHUB_REPO", "${github_repo}")
envVars.put("DOCKER_BUILDKIT", "0")

// Add the node property to Jenkins
globalNodeProperties.add(envVarsNodeProperty)

// Save the configuration
jenkins.save()

// Configure Jenkins URL
def jenkinsLocationConfiguration = JenkinsLocationConfiguration.get()
def publicIP = new URL("http://169.254.169.254/latest/meta-data/public-ipv4").text
jenkinsLocationConfiguration.setUrl("http://" + publicIP + ":8080/")
jenkinsLocationConfiguration.save()
"""

# Create the init.groovy.d script with proper escaping
groovy_setup = f"""
# Create environment variables script
mkdir -p /var/lib/jenkins/init.groovy.d
cat <<'EOF' > /var/lib/jenkins/init.groovy.d/set-env.groovy
{groovy_script}
EOF
"""

docker_config = """
{
    "features": {
        "buildkit": false
    },
    "exec-opts": ["native.cgroupdriver=systemd"],
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "100m"
    },
    "storage-driver": "overlay2"
}
"""
