#!/bin/bash
# Настройки сервера
SERVER_USER="root"
SERVER_HOST="ser-mebel.uz"
SSH_KEY="~/.ssh/id_rsa"  # путь к приватному ключу

# Команда для деплоя
DEPLOY_COMMANDS=$(cat << 'ENDSSH'
cd /var/www/ser-mebel.uz || exit
git pull origin master
docker-compose down
docker build -t khtkarimzhonov/api.ser-mebel.uz:latest ./backend
docker build -t khtkarimzhonov/bot.ser-mebel.uz:latest ./bot

docker-compose -f docker-compose.prod.yml up -d
ENDSSH
)

# Подключение и выполнение команд
ssh -i $SSH_KEY -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_HOST} "$DEPLOY_COMMANDS"
