#!/bin/bash
# 文件名：install-docker-and-compose.sh
# 用法：sudo bash install-docker-and-compose.sh

set -e  # 遇到错误立刻退出

echo "============================================"
echo " 开始在 Debian 12 上安装 Docker + Docker Compose"
echo "============================================"

# 1. 更新系统并安装必要依赖
echo "更新软件包列表并安装依赖..."
apt update -y
apt install -y ca-certificates curl gnupg lsb-release

# 2. 添加 Docker 官方 GPG 密钥
echo "添加 Docker 官方 GPG 密钥..."
mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# 3. 添加 Docker 官方仓库
echo "添加 Docker 官方 apt 仓库..."
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/debian \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

# 4. 再次更新并安装 Docker + Compose 插件
echo "安装 Docker Engine 和 Docker Compose 插件..."
apt update -y
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 5. 启动并开机自启 Docker
echo "启动 Docker 服务..."
systemctl start docker
systemctl enable docker

# 6. 把当前用户加入 docker 组（避免每次都要 sudo）
echo "把当前用户加入 docker 组（重新登录后生效）..."
usermod -aG docker $SUDO_USER || usermod -aG docker $(whoami)

# 7. 验证安装
echo "============================================"
echo "安装完成！版本信息如下："
echo "--------------------------------------------"
docker version --format 'Docker version: {{.Server.Version}}'
echo "--------------------------------------------"
docker compose version

echo "============================================"
echo "安装成功！"
echo "请退出当前终端后重新登录（或新开一个终端），即可直接使用 docker 和 docker compose 命令（无需 sudo）"
echo "例如：docker compose up -d"
echo "============================================"
