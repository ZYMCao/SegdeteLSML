# Label Studio ML 后端开发指南

> SegDete 的 Label Studio ML 后端（`backend/src/lsml/`）用一个独立的图片库验证 SegDete 非拼接的计算机视觉函数（五分类分类器 + 5 类滑窗检测）。它**严格复用** `segdete.vision.*` 业务逻辑，不在后端内重写任何 CV 逻辑。
>
> 每个 Label Studio 任务是一张全景图（由 `lsml/scripts/stitch_to_s3.py` 传到 Garage S3 `in/` 并同步进 LS）。`predict()` 跑分类 + 检测，返回可修正的 `RectangleLabels` 预标注。

## 1. 环境变量配置

加载顺序：环境变量 > `backend/.env` > 默认值。Label Studio 集成相关用 `LABEL_STUDIO_*`，检测阈值等视觉参数用 `SEGDETE_YOLO_*`。

```bash
export LABEL_STUDIO_URL="http://favstimacmini.local:8085"   # LS 主机（用于 s3:// URL 的 presign 解析）
export LABEL_STUDIO_API_KEY="<LS 用户 token>"               # 访问 LS 数据用的 token

# 检测参数（YoloConfig，前缀 SEGDETE_YOLO_）
export SEGDETE_YOLO_CLASSIFIER_THRESHOLD="0.60"   # 每个滑窗 cell 的激活阈值（默认 0.60）
export SEGDETE_YOLO_CLASSIFIER_WINDOW="768"        # 滑窗尺寸
export SEGDETE_YOLO_CLASSIFIER_STRIDE="384"        # 滑窗步长
export SEGDETE_ASSETS_DIR="yoloassets"             # 模型/权重根目录
```

### 1.1 关于"全是离析"（阈值）
检测阈值是 `SEGDETE_YOLO_CLASSIFIER_THRESHOLD`（默认 `0.60`），在 `detector_5class.infer()` 里决定每个滑窗 cell 是否激活（`cls != 0 且 conf >= threshold`），激活的连片 cell 合并成一个检测框；返回给 LS 的 `score` 是组内该类概率的**均值**，通常比 cell 阈值略低。

- 若在 LS 里看到大量低置信度"离析"框，**调高该阈值**即可显著减少误报，例如：
  ```bash
  SEGDETE_YOLO_CLASSIFIER_THRESHOLD=0.30 uv run lsml --host :: --port 9090
  ```
- 注意：`MLClassifier`（`segdete/vision/classifier.py`）目前是存根，恒返 `{pred: 1, confidence: 1.0}`（"需要检测"恒真），所以**只有这个检测阈值在把关**。

### 1.2 检测类别
0 正常、1 轻度离析、2 中度离析、3 重度离析、4 其它。只有离析类别（1–4）会产生框；"正常"（0）cell 不激活，因此正常区域不应出现框。

## 2. 启动

> 以下命令均在 `backend/` 目录下执行。首次使用需先 `uv sync`（注册 `lsml` 命令并安装包）。

```bash
cd backend
uv sync

# 启动 ML 后端（双栈 IPv6 + IPv4）
SEGDETE_YOLO_CLASSIFIER_THRESHOLD=0.30 uv run lsml --host :: --port 9090
```

- 也可直接以脚本方式跑源码（读到实时改动）：
  ```bash
  cd backend
  ./.venv/bin/python src/lsml/_wsgi.py --host :: --port 9090
  ```

### 2.1 启动参数
- `--host`: 绑定地址（默认 `0.0.0.0`）。**跨机 mDNS/IPv6 客户端（如 LS 在另一台机器上用主机名调用）需要 `::` 双栈**，否则 IPv6 请求连不上。
- `--port`: 监听端口（默认 9090）。

### 2.2 健康检查
```bash
curl -s http://127.0.0.1:9090/health
# {"model_dir":"/tmp/ml_backend_runtime","status":"UP","v2":false}
```

## 3. 与 Label Studio 集成（注册）

```bash
curl -sS -X POST http://favstimacmini.local:8085/api/ml/ \
  -H "Authorization: Token <token>" -H "Content-Type: application/json" \
  -d '{
    "url": "http://favstimacbookpro.local:9090",
    "project": 7,
    "title": "segdete-5class",
    "description": "SegDete 5-class classifier + detector",
    "is_interactive": true,
    "auto_update": false
  }'
```
- 注册时 LS 会同步执行 health check（`/health`）与 setup（`/setup`，加载模型），返回 `state: Connected`。
- **注册会自动创建训练 webhook**：`POST /api/ml/<id>/versions` 或 `GET /api/webhooks` 可见 `…favstimacbookpro.local:9090/webhook`（`send_for_all_actions: true`）。

## 4. 验收 / 触发链路

### 4.1 批量预标注
```bash
# 通过 LS 自身的随机任务预测（完整链路：LS → ML → presign → 下载 → 预测）
curl -sS -X POST -H "Authorization: Token <token>" \
  "http://favstimacmini.local:8085/api/ml/<id>/predict/test?random=true"
```
- 返回 `response` 数组，每任务含 `{model_version, result[], score}`。

### 4.2 交互式提示（interactive）
```bash
curl -sS -X POST -H "Authorization: Token <token>" -H "Content-Type: application/json" \
  "http://favstimacmini.local:8085/api/ml/<id>/interactive-annotating" \
  -d '{
    "task": 22170,
    "context": {"result": [{"id": "drag1", "type": "rectanglelabels",
                            "value": {"x": 0, "y": 0, "width": 100, "height": 70}}]}
  }'
```
- 对画的区域裁图 → 在裁图上检测 → 把结果坐标回映到整图百分比，并给每条建议打上 `parent_id=<画的区域 id>`。

### 4.3 webhook 训练开关
- 注册后自动生成的 webhook 在任意标注创建/更新时触发 `ANNOTATION_CREATED`/`ANNOTATION_UPDATED` 到 `/webhook` → 服务端 `fit()`。
- 落盘：每次训练在 `MODEL_DIR`（`/tmp/ml_backend_runtime`）下建 `<job_id>/event.json` + `job_result.json`。
- 也可手动触发训练：`POST /api/ml/<id>/train`。

## 5. 本机 macOS 局域网权限（关键坑：errno 65）

**症状**：LS（launchd 托管）对 `http://favstimacbookpro.local:9090` 做 health check 一直 `[Errno 65] No route to host`，但终端/ssh 里裸 python 却能连上。

**原因**：macOS 15 "本地网络"权限按 **app（bundle）** 识别。launchd 拉起的无 bundle 后台进程拿不到跨机局域网权限（本机 loopback / 公网 / 自己机器局域网 IP 不受影响），而 TCC 路径级授权对无签名解释器无效。

**解决（已落地）**：LS 改用 Homebrew `python@3.14` 的 **`Python.app`** 启动——它的二进制在系统设置"隐私与安全性 → 本地网络"里作为 `python` 条目存在并可开启。launchd 进程只要跑这个 app 的二进制就能连局域网。

- `uv.labelstudio.plist` 的 ProgramArguments 用 `…Python.app/Contents/MacOS/Python`，并设 `PYTHONPATH` 指向 LS 的 venv site-packages。
- LS 跑在 **Python 3.14** 上：多版本兼容上唯一阻塞是 `django-environ` 用了被 3.14 移除的 `pkgutil.find_loader`，**升级 `django-environ>=0.12`** 即可。

## 6. 故障排除

### 6.1 errno 65（LS 连不上 ML 后端）
- 见第 5 节：跨机 LAN 的 launchd 进程必须归到已在"本地网络"里开启的 app 名下。
- 用 `curl http://favstimacbookpro.local:9090/health` 先确认 ML 后端可达。

### 6.2 注册返回 503 / urllib 客户端 503
- LS 对部分客户端（如 `urllib`）可能返回 503，而 `curl` 同接口正常。**验收脚本请用 `curl`**。

### 6.3 模型加载
- 后端启动会在 `/setup` 时加载 `yoloassets/5class_v2_context/best_5class.pth`（首次约数十秒）。缺/corrupt 会 fail-fast。
- 日志：ML 后端启动 `--host ::` 时输出 `Uvicorn running on socket ('::', 9090, …)`。

### 6.4 改了 pyproject 后
- 新增/修改 console script 后需在 `backend/` 执行 `uv sync` 才注册生效。
- 若用 `uv run lsml`（装了包）做开发，改 `src/lsml/*.py` 后需重新 `uv sync`；直接 `python src/lsml/_wsgi.py` 则始终读最新源码。

## 7. 单元测试
```bash
cd backend
uv run pytest src/lsml/test_api.py -v     # 纯逻辑测试（不依赖运行中的 LS）
uv run ruff check src/lsml
```
