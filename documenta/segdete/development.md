#### 1. `segdete`
连接真实相机和本地 MQTT：
```bash
MQTT_TOKEN="0225081901.Segdete.1" SEGDETE_CAMERA_SNS="23779946,23854174" uv run --project backend segdete
```
降级为无相机模式启动 Web 界面：
```bash
MQTT_HOST=localhost MQTT_TOKEN="0225081901.Segdete.1" uv run --project backend segdete
```

#### 2. `test`（单图 Web 检测测试）
所有参数和资产路径全部有默认值（端口默认 8088，模型默认 `yoloassets/5class_v2_context/best_5class.pth`）：
```bash
uv run --project backend test
```

#### 3. `test_imagetest`（离线管道批处理测试）
默认扫描 `data/left`，输出到 `data/out`，模型配置全部自带默认值：
```bash
uv run --project backend test_imagetest
```

#### 4. `test_release_detector`（离线回归评测）
默认扫描 `data/left`，输出 `summary.json`：
```bash
uv run --project backend test_release_detector
```

#### 5. `replay_camera`（无相机端到端回放）

当前 Basler 相机通过 USB/pypylon 接入，并不通过串口传图。回放脚本把
`data/left` 中的每张现场单图切成带重叠区域的虚拟左右帧，然后复用生产的
拼接、分类、检测、落盘和 MQTT 遥测链路。真实双目标定不适用于这种虚拟帧，
脚本会在本次运行中关闭预对齐和双目矫正。

先在本地跑一张图验证，不连接 MQTT：

```bash
uv run --project backend replay_camera \
  --dry-run \
  --limit 1 \
  --output-dir data/replay-out
```

连接本地 ThingsBoard Edge，依次回放整个目录：

```bash
MQTT_HOST=localhost \
MQTT_TOKEN="0225081901.Segdete.1" \
uv run --project backend replay_camera \
  --input-dir data/left \
  --output-dir /srv/static-persister/segdete
```

脚本按现有生产约定把图片写入静态文件目录，并通过 MQTT 上传结果和图片 URL；
它不会把图片二进制直接塞进 MQTT 消息。`--interval` 最小为 1 秒，避免现有按秒
生成的结果文件名互相覆盖。
