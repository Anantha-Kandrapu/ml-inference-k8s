import pulumi


def generate_hosts_entries(worker_ips):
    def process_ips(ips):
        entries = []
        for ip in ips:
            entries.append(f"{ip} worker-{ip.replace('.', '-')}")
        return "\n".join(entries)
    
    # If worker_ips is a list of Output objects, combine them
    return pulumi.Output.all(*worker_ips).apply(process_ips)


def get_master_user_data(master_name, worker_ips):
    hosts_entries = generate_hosts_entries(worker_ips)

    master_user_data = f"""#!/bin/bash
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
echo "Starting master node setup..."

# System updates and basic tools
apt-get update && apt-get install -y apt-transport-https curl

# Add Kubernetes signing key
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.30/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

# Add Kubernetes repository
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.30/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

# Add Docker repository
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"

# Install Docker and Kubernetes components
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

# Disable swap
swapoff -a
sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# Load required kernel modules
cat <<EOF | sudo tee /etc/modules-load.d/containerd.conf
overlay
br_netfilter
EOF
modprobe overlay
modprobe br_netfilter

# Configure sysctl settings
cat <<EOF | sudo tee /etc/sysctl.d/kubernetes.conf
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward = 1
EOF
sysctl --system

# Add worker nodes to hosts file
cat << EOF | sudo tee -a /etc/hosts
{hosts_entries}
EOF

# Configure kubelet
echo "KUBELET_EXTRA_ARGS='--cgroup-driver=cgroupfs'" | sudo tee -a /etc/default/kubelet
sudo systemctl daemon-reload
sudo systemctl restart kubelet

# Configure Docker
echo '{{
  "exec-opts": ["native.cgroupdriver=systemd"],
  "log-driver": "json-file",
  "log-opts": {{
    "max-size": "100m"
  }},
  "storage-driver": "overlay2"
}}' | sudo tee /etc/docker/daemon.json
sudo systemctl daemon-reload
sudo systemctl restart docker

# Configure kubelet service
echo 'Environment="KUBELET_EXTRA_ARGS=--fail-swap-on=false"' | sudo tee -a /etc/systemd/system/kubelet.service.d/10-kubeadm.conf
sudo systemctl daemon-reload
sudo systemctl restart kubelet

# Disable AppArmor
sudo systemctl stop apparmor
sudo systemctl disable apparmor

# Restart containerd
sudo systemctl restart containerd.service

# Initialize Kubernetes control plane
sudo kubeadm init --control-plane-endpoint={master_name} --upload-certs

# Configure kubectl
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# Install Calico networking
kubectl --kubeconfig=$HOME/.kube/config create -f https://raw.githubusercontent.com/projectcalico/calico/v3.25.0/manifests/calico.yaml

# Untaint master node
kubectl taint nodes --all node-role.kubernetes.io/control-plane-

# Save join command to SSM
JOIN_CMD=$(kubeadm token create --print-join-command)
aws ssm put-parameter \
    --region us-west-2 \
    --name "/k8s/join-command" \
    --value "$JOIN_CMD" \
    --type SecureString \
    --overwrite

echo "Master node setup completed"
"""
    return master_user_data


def get_worker_user_data():
    worker_user_data = f"""#!/bin/bash
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
echo "Starting worker node setup..."

# System updates and basic tools
apt-get update && apt-get install -y apt-transport-https curl

# Add Kubernetes signing key
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.30/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

# Add Kubernetes repository
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.30/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

# Add Docker repository
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"

# Install Docker and Kubernetes components
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

# Disable swap
swapoff -a
sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# Load required kernel modules
cat <<EOF | sudo tee /etc/modules-load.d/containerd.conf
overlay
br_netfilter
EOF
modprobe overlay
modprobe br_netfilter

# Configure sysctl settings
cat <<EOF | sudo tee /etc/sysctl.d/kubernetes.conf
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward = 1
EOF
sysctl --system

# Configure kubelet
echo "KUBELET_EXTRA_ARGS='--cgroup-driver=cgroupfs'" | sudo tee -a /etc/default/kubelet
sudo systemctl daemon-reload
sudo systemctl restart kubelet

# Configure Docker
echo '{{
  "exec-opts": ["native.cgroupdriver=systemd"],
  "log-driver": "json-file",
  "log-opts": {{
    "max-size": "100m"
  }},
  "storage-driver": "overlay2"
}}' | sudo tee /etc/docker/daemon.json
sudo systemctl daemon-reload
sudo systemctl restart docker

# Configure kubelet service
echo 'Environment="KUBELET_EXTRA_ARGS=--fail-swap-on=false"' | sudo tee -a /etc/systemd/system/kubelet.service.d/10-kubeadm.conf
sudo systemctl daemon-reload
sudo systemctl restart kubelet

# Disable AppArmor
sudo systemctl stop apparmor
sudo systemctl disable apparmor

# Restart containerd
sudo systemctl restart containerd.service

# Wait for join command and join cluster
until aws ssm get-parameter --region us-west-2 --name "/k8s/join-command" --with-decryption; do
    echo "Waiting for join command..."
    sleep 10
done

JOIN_CMD=$(aws ssm get-parameter --region us-west-2 --name "/k8s/join-command" --with-decryption --query Parameter.Value --output text)
$JOIN_CMD

echo "Worker node setup completed"
"""
    return worker_user_data
