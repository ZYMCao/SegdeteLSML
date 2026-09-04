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

#### 5. `replay` 模式（无相机端到端回放）

当前 Basler 相机通过 USB/pypylon 接入，并不通过串口传图。回放模式由正在运行的
`segdete` 服务直接读取项目根目录的 `data/left`，并执行生产的拼接、分类、检测、
落盘和 MQTT 遥测链路。无需运行额外的图片投递脚本。

先将生产 unit 中的 `SEGDETE_CAMERA_BACKEND` 改为 `replay`，然后部署并启动服务：

```bash
sudo cp deploy/segdete.service /etc/systemd/system/segdete.service
sudo systemctl daemon-reload
sudo systemctl restart segdete
```

服务启动后自动依次处理 `/opt/segdete/data/left` 中的图片。图片来源可用
`SEGDETE_REPLAY_SOURCE` 覆盖；相对路径始终基于项目根目录解析。

开发环境直接启动服务：

```bash
SEGDETE_CAMERA_BACKEND=replay \
MQTT_TOKEN="<device-token>" \
uv run --project backend cli --no-web
```

`data/left` 是单图而不是真实双目照片。服务将每张图片拆为带重叠区域的虚拟左右帧，
并在 replay 模式关闭只适用于真实双目相机的预对齐和矫正。若要恢复物理相机，需将
unit 中的 `SEGDETE_CAMERA_BACKEND` 改回 `basler` 后重启服务。回放的重叠比例固定为
`0.35`。每次服务启动处理目录中的全部支持图片，源文件保持不变。
