# pseudocamera 设计规格（2026-09-10，评审 APPROVED）

## 0. 意图

SegDete 后端 `segdete` 通过 pypylon 驱动两台物理 Basler GigE 相机完成
采图 → 拼接 → 五分类检测。当前最大难题：**没有相机硬件就无法运行/测试系统**。
此前两次尝试（commit `9b6a2d40`、`fc85f1c`）把"回放"做进 segdete 本体
（改 config/CLI/processor，删 3046 行测试与文档），形成双向耦合，
以 `camera_backend="replay"` 残留告终。

本设计意图：

1. 建立**独立项目 `pseudocamera/`**（版本控制归属 `.lsml` 仓库），能让 segdete
   在无 Basler 硬件时以为两台真实 Basler 相机接上了——"伪装成 basler 相机"，
   而非"替换相机接口"。
2. segdete 走**真实相机代码路径**（`camera/basler.py` → pylon →
   `ThreadSafeCameraManager`），有无相机时行为一致；伪装发生在
   **pylon 枚举层**（Basler 官方 Camera Emulation，`PYLON_CAMEMU`）。
3. segdete 代价最小且纯配置驱动（~15 行）；测试素材侧领域知识
   （单张并排双目照片 → 左右帧的 35% 重叠切分）迁出 segdete，
   只存在于 pseudocamera。
4. 清除旧耦合：删除 `camera_backend="replay"`、`ReplayCameraManager`
   及专属测试/配置字段。
5. 验收边界（用户明示）止于 **"camera mock → segdete"——即 segdete 相机层的帧契约**；
   **不涉及 MQTT**；下游（stitch/detect/telemetry）不在验收范围，
   完整处理循环仅作文档化可选命令。

## 1. 已验证事实

| # | 事实 |
|---|---|
| F1 | `PYLON_CAMEMU=2` 在 macOS 可用：枚举 2 台 `BaslerCamEmu`，序列号固定 `0815-0000`/`0815-0001`。env 在 `EnumerateDevices` 时读取，早设为纪律。 |
| F2 | `ThreadSafeCameraManager(sn_list=['0815-0000','0815-0001'], exposure_time=5000, frame_rate=30, camera_params={...})` 零修改初始化，`grab_frames()` 返回 `[{sn, idx, bgr}]` 契约。 |
| F3 | `configure_camera`（`basler.py:99-179`）赋值全被 `_safe_call`/`_try_set_*`（`basler.py:87-96`）包裹，缺 feature 静默跳过；所需 feature emu 全部存在。 |
| F4 | `PixelFormat` 接受 `"RGB8Packed"`（`"RGB8"` 字面量被静默跳过，params 里的 `RGB8Packed` 随后生效）。 |
| F5 | 官方顺序 `TestImageSelector=Off` → `ImageFileMode=On` → `ImageFilename=<目录>`（无子目录），按文件名序循环；官方文档 `documenta/basler/Camera Emulation....md:79-99`。 |
| F6 | `_REPLAY_OVERLAP=0.35` 与 `split_virtual_stereo` 只存在于 `camera/replay.py:13,16-23,100`；主业务 stitch overlap 是运行时特征匹配。 |
| F7 | **MQTT 阻塞约束**（仅文档化）：`cli` 在处理线程启动前同步调 `tb_client.connect()`（`cli.py:180-181`），无 broker 永久阻塞；缺 `MQTT_TOKEN` 直接 exit(1)。本设计不依赖此路径。 |
| F8 | 测试在 `backend/src/test/`，5 个文件引用 replay（见 §4 删除清单）。 |
| F9 | 拆分机制 = `.git/info/exclude` 与 `.lsml/info/exclude`；`scripta/ops/git.ts` 已不存在。源码改动属 `.git`，`backend/src/test/` 改动属 `.lsml`。 |
| F10 | CLI 入口 `cli = segdete.cli:main`；部署 `cli --no-web`（`SEGDETE_CAMERA_BACKEND=basler` 在收窄后仍合法）。 |
| F11 | `configure_camera` 仅一处调用 `basler.py:300`（`initialize()` 的 `for i, cam in enumerate` 循环，`i` 即 sn_list 索引）。 |
| F12 | emu 默认 ROI = Width 1024 × Height 1040；文件模式帧超 ROI 直接裁剪（不缩放）。 |

## 2. 设计决策

- **A（选定）PYLON_CAMEMU**。B（否决，未来 spike）Aravis 网络伪装：pylon↔Aravis 互通未验证。C（否决）importlib 插件 seam：绕开真路径。
- 帧序 = 目录文件名序循环（确定性回放）。
- prep 归一化：帧 fit 缩放（保纵横比，`cv2.INTER_AREA`）至 emu ROI 内，目标尺寸为 prep CLI 参数（默认 1024×1040）。

## 3. pseudocamera 项目（归属 `.lsml`）

```
pseudocamera/
  pyproject.toml          # hatchling + src 布局; requires-python >=3.13
                          # 依赖 numpy, opencv-python-headless; dev: pytest
                          # [tool.pytest.ini_options] pythonpath=["src"]
                          # wheel force-include，同 backend
  README.md               # 运行手册（含 F7 说明；uv 位置提示；harness 启动契约）
  .gitignore              # frames/, .venv/
  src/pseudocamera/       # 无 __init__.py（隐式命名空间包）
    cli.py                # prep / run / harness 子命令；含 if __name__ == "__main__" 守卫
    prep.py               # 素材 → 帧目录（含归一化）
    run.py                # env 组装 + subprocess
    harness.py            # 相机层验收回路；无模块级 pypylon/segdete import
                          # （全部延迟到 env 设置之后，供 --help 可用）
  tests/
    test_prep.py
    test_run.py
    test_harness.py
  frames/                 # prep 产物（gitignore）
```

**prep**（`pseudocamera prep <source> -o frames/ [--overlap 0.35] [--max-width 1024 --max-height 1040] [--left <dir> --right <dir>]`）：
并排照片目录：`crop_w = round(W*(1+overlap)/2)`；左 `image[:, :crop_w]`、右 `image[:, W-crop_w:]`；
解码 `cv2.imdecode(np.fromfile(...))`；fit 缩放 `INTER_AREA`；
输出 `frames/left|right/frame_%04d.png` + `manifest.json`（源、overlap、目标尺寸、每帧 md5）。

**run**（`pseudocamera run [--camemu 2] [-- command...]`）：
仅覆盖 5 个 env（其余全继承用户真实配置）：
`PYLON_CAMEMU=2`、`SEGDETE_CAMERA_SNS=0815-0000,0815-0001`、
`SEGDETE_PIXEL_FORMAT=RGB8Packed`、`SEGDETE_PSEUDOCAMERA_LEFT_DIR/RIGHT_DIR=<abs>`。
frames/ 缺失自动 prep；默认命令 `<repo>/backend/.venv/bin/cli --no-web`；
信号/退出码透传；响亮告警（PYLON_CAMEMU 冲突 / MQTT_TOKEN 缺失 / 无 broker 阻塞）。

**harness**（相机层验收，`pseudocamera harness [--frames 3] [--frames-dir frames/]`）：
os.environ 先设 6 变量（上 5 个 + `SEGDETE_LOG_LEVEL=INFO`）再 import。
fail-loud 前置断言：`'pseudocamera_left_dir' in AcquisitionConfig.model_fields`（pydantic v2
类级 `hasattr` 对已声明字段返回 False，不可用），缺失即报"陈旧 segdete，请 uv sync"。
枚举断言：结果必须包含序列号 `0815-0000`、`0815-0001` 的 BaslerCamEmu 设备
（真机共存允许额外设备）。按 `cli.py:138-143` 实参构造
`ThreadSafeCameraManager`；`start()` → `grab_frames()` × (N×每目录帧数) →
逐项断言：每次恰 2 帧且 sn/idx 契约正确；帧数组与 prep 产物逐像素相等
（含跨目录回卷；该断言同时是静默误配置/ROI 裁剪的响亮校验）；
`stop()`/`close()`；退出码 0/1。**零 `segdete.pipeline` import。**

**harness 启动契约**（后端解释器，非 pseudocamera venv）：
`cd pseudocamera && PYTHONPATH=src:../backend/src ../backend/.venv/bin/python -m pseudocamera.cli harness --frames 3`
（`backend/src` 在先 → 新源码优先于 site-packages 陈旧副本；fail-loud 断言退居兜底；
`run` 模式的 `cli` 目标仍要求 `uv sync`。）

## 4. segdete 改动（v4：回退 4e90ce2 + 必要接缝中性化，评审 Round 4 APPROVED）

必要性判定（用户裁定 + 审查取证）：与 pre-replay 基线 `4e90ce2` 对比，
**不必要的一律回退，只保留两小块**。

回退组（与 4e90ce2 字节一致/产物清除）：
1. `cli.py`：`git checkout 4e90ce2 --` 整文件还原（posix root 警告、delay
   重排、import 顺序、丢注释四项 replay 期痕迹全部归零；`git log -S geteuid`
   证实警告出自 9b6a2d4）。
2. `acquisition.py`：删 `camera_backend` 字段与 `Literal` import
   （9b6a2d4 引入；全仓仅定义+1 测试引用；`extra="ignore"` 下删 deploy 行安全）。
3. `deploy/segdete.service`（.git 侧）：删 `SEGDETE_CAMERA_BACKEND=basler` 行。
4. 删 `test_replay_camera_rejects_invalid_backend` 测试。
5. `processor.py`：无动作（replay 相关 diff 已 = 0；合法业务提交
   72254f4/d508db1/2411f86 保留）。

保留组（必要接缝，中性命名）：
1. `acquisition.py`：`image_file_left_dir: str = ""`、`image_file_right_dir: str = ""`
   （GenICam 原生 `ImageFile*` 命名）；`camera_params()` 追加
   `"image_file_dirs": [left, right]`。
2. `basler.py`：`configure_camera` 保持 pre-replay 签名 `(cam, params)`（diff = 0）；
   注入块（6 行）位于 `initialize()` 的 `for i, cam in enumerate` 循环内、
   `configure_camera(cam, self.camera_params)` 之后：
   `_try_set_enum(cam.TestImageSelector, "Off")` →
   `_try_set_enum(cam.ImageFileMode, "On")` →
   `_safe_call(cam.ImageFilename.SetValue(str(dirs[i])))`。
   `set_roi` 重建路径（temp_params 浅拷贝）自动携带注入，已验证。

终态 diff（v4 实测）：
- `cli.py` / `processor.py` vs 4e90ce2：replay 痕迹零命中（字节一致/仅业务提交）
- `acquisition.py` vs 4e90ce2：+2 字段 +1 行 params
- `basler.py` vs HEAD：仅 +6 行 initialize 注入
- `grep -rn pseudocamera backend/src --include='*.py'` → 0 命中
- `grep -rn camera_backend backend/src` → 0 命中；deploy 无 `CAMERA_BACKEND` 行

测试同步（v4）：`test_config.py` 改为
`test_image_file_dirs_from_environment`（`SEGDETE_IMAGE_FILE_*`）。

## 5. 验收清单（全部止于相机层，v4 更新）

1. 无相机：harness `--frames 3` → 日志含 `pylon found 2 device(s): ['0815-0000', '0815-0001']`；
   初始化成功；grab 多次目录循环、帧逐像素等于 prep 产物；退出码 0。
   harness env 六变量含 `SEGDETE_IMAGE_FILE_LEFT_DIR/RIGHT_DIR`。
2. env 全空 → 现有单测全绿 + `configure_camera` 真机行为逐行不变。
3. `replay.py` 不存在；`camera_backend` 字段不存在（`grep camera_backend backend/src` 为空）
   且 deploy 无 `SEGDETE_CAMERA_BACKEND`；processor 无 `empty_capture_is_normal`；
   `grep ReplayCamera backend/src` 为空。
4. `backend/src` 无 `0.35`/`split_virtual_stereo`；pseudocamera 有切分几何 + fit 归一化测试。
5. diff 无 MQTT 文件；`harness.py` 无 `segdete.pipeline` import。

## 6. 风险

R1 完整循环（stitch/detect/telemetry）明确不在验收内；文档化可选命令由用户运行时决定。
R2 macOS PNG 官方未列但实测可用；README 提示。
R3 PYLON_CAMEMU 枚举时读取；早设为纪律。
R4 序列号固定，左右映射 = sn_list 索引。
R5 真机共存天然隔离。
R6 emu ROI 裁剪：归一化 + 帧保真断言双保险。
R7 陈旧 wheel：uv sync + fail-loud 检查。

## 7. 超出范围

MQTT 伪造/broker；processing loop/stitch/detect 自动化验收；Aravis spike；
恢复已删 docs；修改 AGENTS.md；任何 git commit（除非用户明确要求）。

## 8. 评审记录

- Round 1（ses_f754182b1ffeFmvWvWa11fKS1W）：NEEDS REVISION（2 BLOCKER + 3 MAJOR + 4 MINOR）。
- Round 2：NEEDS REVISION（1 MAJOR + 4 MINOR）。
- 边界修正：用户确认验收止于相机层，完整循环出验收。
- Round 3：**APPROVED**（附 3 条非阻塞备注，已并入本文：
  `model_fields` 断言写法；README 注明 grep 清洁度指源码树；`__main__` 守卫 + T3 检查用后端解释器）。

## 9. v4 评审记录（2026-09-10）

用户三项质疑成立：(1) `AcquisitionConfig` 提及 pseudocamera 是命名泄漏；
(2) `configure_camera` 的 `idx` 参数不必要；(3) 要求对比 pre-replay（4e90ce2）
并回退一切不必要改动。planner 判定：必要 = replay 清除 + 最小中性注入接缝；
其余（camera_backend 字段、idx 参数、cli 美学残留、posix 警告）全部回退。
Round 4（同一审查者）：**APPROVED**——回退边界经 git 取证核实（cli.py 仅
9b6a2d4/fc85f1c 触碰过，字节还原零损失；posix 警告出自 9b6a2d4；
camera_backend 仅 2 处引用；deploy 行删除安全），4 条非阻塞备注（改名 5 处
定位、验收措辞、2411f86 业务清单、`_try_set_enum` 风格）已并入。
v4 实测：backend 108 passed；harness exit 0（48 抓帧逐像素相等）；
`grep pseudocamera backend/src` 与 `grep camera_backend backend/src` 均零命中。

## 10. v5 终态（2026-09-10，Round 5 NEEDS→Round 6 APPROVED）

用户第四项质疑（成立）：basler.py 的 6 行注入块"不是完全必要"。planner 探针
证实并采纳 v5——**伪装机制整体移出 segdete**：

- segdete 四文件对 pre-replay（4e90ce2）终态：`cli.py`/`processor.py`/
  `acquisition.py` **零 diff**（processor 仅剩合法业务提交 72254f4/d508db1/
  2411f86，replay/masquerade 相关 token 零命中）；`basler.py` 对 HEAD 零 diff
  （摘除 6 行后即回 HEAD 加固态）。
- `grep -rnE "image_file_dirs|image_file_left_dir|image_file_right_dir|pseudocamera|camera_backend"
  backend/src --include='*.py'` → 零命中（`scripts/test_imagetest.py` 的合法
  `image_files` 不匹配、不许动）。
- pseudocamera 新增：`shim.py`（幂等 patch `pypylon.pylon.InstantCamera.Open`；
  `BaslerCamEmu` + `PSEUDOCAMERA_LEFT_DIR/RIGHT_DIR` 时按序列号
  0815-0000→左/0815-0001→右设置 `TestImageSelector=Off`→`ImageFileMode=On`→
  `ImageFilename`；激活/失败 stderr 响亮日志；真机与环境缺失 no-op）、
  `launcher.py`（装 shim → `segdete.cli.main()` 显式链）。
- `run.py`：env 改 `PSEUDOCAMERA_*`；默认目标
  `backend/.venv/bin/python -m pseudocamera.launcher --no-web`；
  `launch()` 前置 `pseudocamera/src` 到 PYTHONPATH。
- `harness.py`：装 shim 后 import segdete；删 `assert_fresh_segdete`——
  fail-loud 由帧保真断言独立承担（shim 失效等原因坍缩为 gradient 帧，
  不可能逐像素等于 per-index 不同的照片帧）。
- 陷阱修复：pseudocamera pyproject 补 `[tool.uv] cache-keys`（此前 console
  script 会执行陈旧 wheel；修复后 src 变更自动重装，与 backend 一致）。
- Round 5 两条 MINOR（acquisition.py 空行还原、grep 模式收窄）修正后
  Round 6 APPROVED。

v5 实测：backend 107 passed；pseudocamera 16 passed（含 4 项 shim 单测）；
harness exit 0（48 抓帧逐像素 + 循环序 + 2 条 shim 激活日志）；
`python -m pseudocamera.launcher --help` 走通 segdete CLI 并 exit 0；
`pseudocamera run -- <自定义命令>` 环境与 PYTHONPATH 接线正确。

## 11. v6 调整（2026-09-10，用户裁定）

1. 帧产物位置：默认输出改为 **repo 根 `data/frames/`**（`prep -o`、`run --frames`、
   `harness --frames-dir` 三处默认值），不再在 `pseudocamera/` 内生成任何东西；
   `data/frames` 被根 `.gitignore` 的 `/data/` 条目天然忽略（两个仓库均不产生噪音）。
   选定 `data/frames` 子目录而非直接写 `data/left|right`，避免与既有源照片目录
   `data/left`（1704×1279 jpg）混装并造成 prep 自反馈。
2. 移除 `run` 的自动 prep 魔法（原先硬编码 `data/left` 自动生成）——改为缺失时
   响亮报错并提示 `prep` 命令。
3. 测试位置：遵照通用 pytest 惯例保留在 **`pseudocamera/tests/`**（用户裁定），
   不迁 `src/test`；全部测试由 `.lsml` 仓库追踪；命令
   `uv run --directory pseudocamera pytest`。

v6 实测：pseudocamera 16 passed；harness 从 repo 根运行 exit 0（48 抓帧 + 2 条
shim 激活日志，默认 `data/frames`）；`run` 对缺失 frames 报
`no prepared frames under ...; run pseudocamera prep ... first`。

## 12. v7 调整（2026-09-10，用户裁定：统一为 src/tests）

项目统一测试布局为 **`src/tests/`**（复数）：
- `pseudocamera/tests/` → `pseudocamera/src/tests/`
- `backend/src/test/` → `backend/src/tests/`（原为单数 `test`）
- `.git/info/exclude` 的 `/backend/src/test/` → `/backend/src/tests/`
- 两处 `pythonpath=["src"]` 配置不变；Hatchling `force-include` 只打包
  `src/<pkg>`，测试不随包发布（backend 先例）。
- `.lsml` 追踪：backend 15 个测试以 rename 暂存；pseudocamera 4 个测试暂存于
  新路径。

v7 实测：backend 107 passed；pseudocamera 16 passed（均从 `src/tests` 采集）。
