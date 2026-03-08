# Docker Compose 目录

本目录提供本地开发环境的一键编排。

## 文件说明
- `docker-compose.yml`：阶段一 Week 1 本地依赖与服务编排（Redis/MySQL/Kafka/Zipkin + 三个业务服务）。
- `.env.example`：环境变量模板。
- `prometheus.yml`、`grafana/`：阶段一 Week 4 补齐监控相关编排。

## 使用方式
1. 在本目录复制环境变量文件：
   - `cp .env.example .env`
2. 在仓库根目录执行：
   - `docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env up -d --build`
3. 查看状态：
   - `docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env ps`
4. 停止并清理：
   - `docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env down`

## 访问入口
- Gateway: `http://localhost:8080`
- Moderation: `http://localhost:8081`
- Model: `http://localhost:8082`
- Zipkin: `http://localhost:9411`
