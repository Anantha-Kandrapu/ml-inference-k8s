def get_jenkins_user_data(ecr_url, github_repo="https://github.com/Anantha-Kandrapu/ml-inference-k8s"):
    return f"""#!/bin/bash
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
echo "Starting Jenkins setup..."

# Install Java 17
apt-get update
apt-get install -y openjdk-17-jdk

# Install Jenkins
curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io.key | sudo tee \
  /usr/share/keyrings/jenkins-keyring.asc > /dev/null
echo deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc] \
  https://pkg.jenkins.io/debian-stable binary/ | sudo tee \
  /etc/apt/sources.list.d/jenkins.list > /dev/null
apt-get update
apt-get install -y jenkins

# Install Docker
apt-get install -y docker.io
usermod -aG docker jenkins
systemctl enable docker
systemctl start docker

# Install AWS CLI and other tools
apt-get install -y awscli git jq

# Wait for Jenkins to start
sleep 30

# Create Jenkins job configuration
mkdir -p /var/lib/jenkins/jobs/ml-inference
cat <<EOF > /var/lib/jenkins/jobs/ml-inference/config.xml
<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <description>ML Inference Pipeline</description>
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
          <name>*/main</name>
        </hudson.plugins.git.BranchSpec>
      </branches>
    </scm>
    <scriptPath>infrastructure/Jenkinsfile</scriptPath>
  </definition>
</flow-definition>
EOF

# Store ECR URL and GitHub repo in Jenkins global environment
mkdir -p /var/lib/jenkins/init.groovy.d
cat <<EOF > /var/lib/jenkins/init.groovy.d/set-env.groovy
import jenkins.model.Jenkins
def instance = Jenkins.getInstance()
def globalNodeProperties = instance.getGlobalNodeProperties()
def envVarsNodePropertyList = globalNodeProperties.getAll(hudson.slaves.EnvironmentVariablesNodeProperty.class)
def envVars = envVarsNodePropertyList.get(0)?.getEnvVars()
if (envVars == null) {{
    envVars = new hudson.slaves.EnvironmentVariablesNodeProperty().getEnvVars()
    globalNodeProperties.add(new hudson.slaves.EnvironmentVariablesNodeProperty(envVars))
}}
envVars.put("ECR_URL", "{ecr_url}")
envVars.put("GITHUB_REPO", "{github_repo}")
instance.save()
EOF

# Download Jenkins plugin CLI
curl -L https://github.com/jenkinsci/plugin-installation-manager-tool/releases/download/2.12.11/jenkins-plugin-manager-2.12.11.jar -o /usr/local/bin/jenkins-plugin-cli.jar

# Create wrapper script for plugin CLI
cat <<EOF > /usr/local/bin/jenkins-plugin-cli
#!/bin/bash
java -jar /usr/local/bin/jenkins-plugin-cli.jar "\$@"
EOF
chmod +x /usr/local/bin/jenkins-plugin-cli

# Install Jenkins plugins
jenkins-plugin-cli --plugins \
workflow-aggregator \
git \
github \
docker-workflow \
pipeline-aws \
credentials-binding \
amazon-ecr \
docker-plugin \
aws-credentials \
pipeline-stage-view \
blueocean

# Set permissions
chmod +x /usr/local/bin/jenkins-plugin-cli
chown -R jenkins:jenkins /var/lib/jenkins

# Restart Jenkins
systemctl restart jenkins

# Wait for Jenkins to restart
sleep 30

echo "Jenkins setup completed"
"""