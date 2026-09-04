#### 1. `cli`
连接真实相机和本地 MQTT：
```bash
MQTT_TOKEN="0225081901.Segdete.1" SEGDETE_CAMERA_SNS="23779946,23854174" uv run --project backend cli
```
降级为无相机模式启动 Web 界面：
```bash
MQTT_HOST=localhost MQTT_TOKEN="0225081901.Segdete.1" uv run --project backend cli
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

当前 Basler 相机通过 USB/pypylon 接入，并不通过串口传图。回放模式由正在运行的
`segdete` 服务消费图片并执行生产的拼接、分类、检测、落盘和 MQTT 遥测链路；
`replay_camera` 只投递现场图片，不加载模型或执行业务逻辑。

生产 unit 将 `SEGDETE_CAMERA_BACKEND` 配置为 `replay`。部署并启动服务：

```bash
sudo cp deploy/segdete.service /etc/systemd/system/segdete.service
sudo systemctl daemon-reload
sudo systemctl restart segdete
```

以服务用户投递一张图片：

```bash
sudo -u easttrans /opt/segdete/backend/.venv/bin/replay_camera \
  --limit 1
```

图片来源默认为 `data/left`，可在执行 `replay_camera` 时用
`SEGDETE_REPLAY_SOURCE` 或 `--input-dir` 覆盖。
脚本结束表示投递完成；最终处理状态查看 `segdete` 日志和 MQTT 结果。

开发环境分别启动消费者和生产者：

```bash
SEGDETE_CAMERA_BACKEND=replay \
MQTT_TOKEN="<device-token>" \
uv run --project backend cli --no-web
```

```bash
uv run --project backend replay_camera
```

`data/left` 是单图而不是真实双目照片。服务将每张图片拆为带重叠区域的虚拟左右帧，
并在 replay 模式关闭只适用于真实双目相机的预对齐和矫正。若要恢复物理相机，需将
unit 中的 `SEGDETE_CAMERA_BACKEND` 改回 `basler` 后重启服务。回放的重叠比例固定为
`0.35`，服务等待图片的轮询超时固定为 `1` 秒。
