# LabelStudio + Garage S3 跨域（CORS）问题排查与解决

## 1. 背景与症状

- LabelStudio 部署在 `http://favstimacmini.local:8085`（uv 启动，见 `~/Library/LaunchAgents/uv.labelstudio.plist`）
- 对象存储为自建 Garage（macOS 本地编译版 v2.3.0，见 `~/Library/LaunchAgents/rust.garage.plist`），S3 端点 `http://favstimacmini.local:3900`，bucket `segdete`（LabelStudio 项目 7 的 S3 import/export storage）
- 打开标注页 `http://favstimacmini.local:8085/projects/7/data?tab=2` 时，浏览器控制台报错：

```
Access to image at 'http://favstimacmini.local:3900/segdete/in/...jpg?response-content-type=...&X-Amz-...'
(redirected from 'http://favstimacmini.local:8085/tasks/22167/resolve/?fileuri=...')
from origin 'http://favstimacmini.local:8085' has been blocked by CORS policy:
No 'Access-Control-Allow-Origin' header is present on the requested resource.
```

## 2. 根因分析

1. LabelStudio 数据库里任务的图片地址是 `s3://segdete/in/...` 形式，前端展示时请求
   `/tasks/<id>/resolve/?fileuri=<base64>`，服务端返回 **302 跳转**到 Garage 的预签名 URL（带
   `X-Amz-*` 签名参数、`response-content-type=image/jpeg`、`X-Amz-Expires=60`）。
2. 因此图片由浏览器**直接从 Garage（:3900）跨源加载**，与 LabelStudio 无关——问题出在
   Garage 侧，任何 LabelStudio 配置（如 `S3_TRUSTED_STORAGE_DOMAINS`）都无法改变 S3 响应的 CORS 头。
3. Garage v2 的 CORS 支持是**按 bucket 配置**的（源码：`src/api/common/cors.rs` 的
   `find_matching_cors_rule()` 匹配请求的 `Origin` + 方法 + 请求头，命中后在响应中写入
   `Access-Control-Allow-Origin/Methods/Headers/Expose-Headers`，见 `add_cors_headers()`；
   响应路径在 `src/api/s3/api_server.rs`）。`segdete` bucket 之前没有 CORS 规则，故返回 403/200
   均不带 `Access-Control-Allow-Origin`，浏览器拦截。

## 3. 关键认知：Garage 如何配置 CORS

- **Garage CLI 没有 CORS 子命令**（`garage bucket --help` 只有 alias/allow/create/delete/deny/info/
  list/set-quotas/unalias/website；顶层 `garage --help` 也没有）。
- 官方支持的配置途径有两个，二选一即可：
  1. **admin API**：`PUT /v0/bucket?id=<bucket_id>`（body 为 `corsRules` JSON）；v2 风格路径
     为 `/v2/Bucket`/`/v2/UpdateBucket`（注意 PascalCase，容易踩坑），推荐直接用 v0。
  2. **标准 S3 API** `PutBucketCors`（Garage 实现了该端点，`src/api/s3/cors.rs`），可用
     `aws s3api put-bucket-cors --endpoint-url ...` 调用。
- 最规范、免裸 curl 的入口是 Garage 自带 CLI 工具 **`garage json-api <endpoint> <payload>`**
  （"Directly invoke the admin API using a JSON payload"），payload 格式与 admin API 请求体一致。

## 4. 解决方案（本次实际采用）

```bash
GARAGE=/Users/administrator/RustRoverProjects/Garage/target/release/garage
CONF=/Users/administrator/.garage/garage.toml
BUCKET_ID=<segdete 的 bucket id，见步骤 1>

# 步骤 1：查询 bucket id（也可用 garage bucket info segdete）
$GARAGE -c $CONF json-api GetBucketInfo '{"globalAlias":"segdete"}'

# 步骤 2：写入 CORS 规则（幂等，可重复执行）
# ⚠️ 一条规则只能配一个 AllowedOrigin（原因见下文"关键教训"）
$GARAGE -c $CONF json-api UpdateBucket "{\"id\":\"$BUCKET_ID\",\"body\":{\"corsRules\":[{\"ID\":\"ls-local\",\"MaxAgeSeconds\":3600,\"AllowedOrigin\":[\"http://favstimacmini.local:8085\"],\"AllowedMethod\":[\"GET\"],\"AllowedHeader\":[\"*\"],\"ExposeHeader\":[\"*\"]},{\"ID\":\"ls-remote\",\"MaxAgeSeconds\":3600,\"AllowedOrigin\":[\"https://labelstudio.favstii.com\"],\"AllowedMethod\":[\"GET\"],\"AllowedHeader\":[\"*\"],\"ExposeHeader\":[\"*\"]}]}}"
```

规则字段说明（对应标准 S3 `CORSRule`，XML 标签名直接作为 JSON 字段名）：
- `AllowedOrigin`：允许的来源（`*` 或**单个**具体 origin，如 `http://favstimacmini.local:8085`）
- `AllowedMethod`：允许的 HTTP 方法，如 `GET`
- `AllowedHeader` / `ExposeHeader`：允许/暴露的请求/响应头，`*` 通配
- `MaxAgeSeconds`：预检结果缓存时长

无需重启 Garage，配置实时生效（存储在 bucket 元数据中）。

### 关键教训：一条 CORS 规则只能配一个 origin

Garage 源码 `src/api/common/cors.rs` 的 `add_cors_headers()` 把规则里**所有** `AllowedOrigin`
用 `join(", ")` 拼成一个 `Access-Control-Allow-Origin` 响应头值。而浏览器（CORS 规范）要求
该头**只能有单个值**（一个 origin 或 `*`），逗号拼接的多值会被判定无效并直接拒绝请求：

- 若一条规则写 `["http://favstimacmini.local:8085", "https://labelstudio.favstii.com"]`，
  响应为 `access-control-allow-origin: http://favstimacmini.local:8085, https://labelstudio.favstii.com`，
  **浏览器认为 CORS 失败**（LabelStudio 前端 `<img crossOrigin="anonymous">` 触发 onError，
  页面显示 "There was an issue loading URL from $image value"）。
- **正确做法**：需要放行多个 origin 时，写多条规则，每条规则恰好一个 origin。
  Garage 按请求的 `Origin` 头匹配第一条命中规则（`cors_rule_matches`：origin、方法、请求头全匹配），
  响应头即为该规则唯一的 origin，浏览器即可通过校验。
- **curl 验证的陷阱**：curl 不做 CORS 校验，头里写了什么就显示什么。因此验证时必须检查
  `access-control-allow-origin` 的**值**是否恰好等于请求的 `Origin`（单值），否则会出现
  "curl 显示有 ACAO 头，浏览器却仍然失败"的假阳性。

### 关键教训：预签名 URL 有效期（presign_ttl）

LabelStudio 的 S3 storage 配置里有 `presign_ttl`（分钟），`resolve` 端点为每个 URL 签发
`X-Amz-Expires=<ttl*60>` 秒的有效期（默认 1 分钟）。图片加载慢、页面停留久或缓存复用时会
过期返回 403（`AccessDenied: Invalid signature` / 过期）。建议调大，本项目已设为 15 分钟。
查看/修改：manage.py shell 读 `io_storages.s3.models.S3ImportStorage.presign_ttl`（或 LabelStudio
项目设置 → Cloud storage → Presign TTL）。

## 5. 验证

```bash
# 5.1 确认规则已持久化
$GARAGE -c $CONF json-api GetBucketInfo '{"globalAlias":"segdete"}'   # 应看到 corsRules

# 5.2 生成预签名 URL 并带 Origin 头请求（模拟浏览器行为）
#   - 用 LabelStudio 中 S3 storage 的凭证（access key + secret）
#   - boto3: generate_presigned_url("get_object", Params={..., "ResponseContentType": "image/jpeg"})
curl -sS -D - -o /dev/null "<预签名URL>" -H "Origin: http://favstimacmini.local:8085"
# 期望输出（ACAO 必须是单值，恰好等于请求的 Origin）：
#   HTTP/1.1 200 OK
#   content-type: image/jpeg
#   access-control-allow-origin: http://favstimacmini.local:8085

# 每个需要放行的 origin 都测一遍：
curl -sS -D - -o /dev/null "<预签名URL>" -H "Origin: https://labelstudio.favstii.com"
#   access-control-allow-origin: https://labelstudio.favstii.com

# 未放行的 origin 不应出现 ACAO 头（浏览器会拦截）：
curl -sS -D - -o /dev/null "<预签名URL>" -H "Origin: http://evil.example.com"
#   （无 access-control-allow-origin 行）
```

## 6. 回滚

```bash
$GARAGE -c $CONF json-api UpdateBucket "{\"id\":\"$BUCKET_ID\",\"body\":{\"corsRules\":[]}}"
```

## 7. 备注

- 排查经过：
  1. 症状 1（浏览器 console 报 "No 'Access-Control-Allow-Origin' header"）→ 配置 bucket CORS 规则（此时错误被 garage 忽略）。
  2. 症状 2（页面报 "There was an issue loading URL from $image value"，Garage 日志显示同一 URL 被请求 4 次均失败）→ 发现 Garage 把多条 `AllowedOrigin` 拼接进单个 ACAO 头，浏览器判定无效；按每条规则一个 origin 拆开解决。
- 签名细节：Garage 预签名 URL 的查询参数顺序为 `response-content-type` 在前、`X-Amz-*` 在后
  （boto3 默认输出即如此）；手写 SigV4 时需完全复现该 canonical query 串，否则 403 `Invalid signature`。
- LabelStudio 前端加载图片使用 `<img crossOrigin="anonymous">`（`web/libs/editor/src/components/ImageView/Image.jsx`），
  图片请求始终处于 CORS 模式，响应缺少/非法 ACAO 头都会触发 onError。
- 排查过程中用到的其余只读信息：
  - LabelStudio S3 凭证/配置查询：`uv run python label_studio/manage.py shell` 读取
    `io_storages.s3.models.S3ImportStorage`（需注入 `DJANGO_DB=postgresql` 等环境变量）。
  - Garage 相关源码：`src/api/common/cors.rs`、`src/api/s3/api_server.rs`、
    `src/api/admin/router_v0.rs`（`PUT /v0/bucket`）、`src/api/admin/api.rs`（`UpdateBucketRequestBody`）。
  - Garage 请求日志：`~/Library/Logs/Garage/garage.log`（仅记录请求行，不含状态码）；
    调用计数可查 admin API `GET /metrics`（Prometheus 格式，`api_s3_request_counter`）。
