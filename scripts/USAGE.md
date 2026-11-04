# dev-local.sh 使用说明

这个项目推荐使用脚本 `scripts/dev-local.sh` 本地启动。

## 1. 进入项目目录

```bash
cd /Volumes/2TB/code/java/multimodel-safetyrisk
```

## 2. 首次启动前（可选但推荐）

如果 `8080/8081/8082` 端口被旧进程占用，先清理：

```bash
for p in 8080 8081 8082; do
  pid=$(lsof -ti tcp:$p)
  if [ -n "$pid" ]; then
    kill $pid
  fi
done
```

## 3. 启动项目

```bash
./scripts/dev-local.sh start
```

说明：
- 会启动依赖容器（MySQL/Redis/Kafka/Zipkin 等）
- 会启动本地 3 个服务：
  - `moderation-service`（8081）
  - `model-service`（8082）
  - `gateway-service`（8080）

## 4. 查看状态

```bash
./scripts/dev-local.sh status
```

## 5. 查看日志

```bash
./scripts/dev-local.sh logs gateway-service
./scripts/dev-local.sh logs moderation-service
./scripts/dev-local.sh logs model-service
```

按 `Ctrl + C` 退出日志跟踪。

## 6. 停止服务

只停止 3 个本地 Java 服务：

```bash
./scripts/dev-local.sh stop
```

停止本地服务 + 依赖容器：

```bash
./scripts/dev-local.sh stop-all
```

## 7. 常见问题

1. 报错 `Port 808x was already in use`

先执行“端口清理”命令，再重新 `start`。

2. 脚本无法执行（权限问题）

```bash
chmod +x ./scripts/dev-local.sh
```

3. 需要查看帮助

```bash
./scripts/dev-local.sh --help
```

## 8. 压测脚本（Week4）

JMeter 压测脚本位于：

```bash
scripts/jmeter/
```

详细执行说明见：

```bash
scripts/jmeter/README.md
```
