## 数据上传示例

### preAlign

```json
{
  "enabled": true,
  "yaw_left_deg": -15.0,
  "yaw_right_deg": 15.0,
  "pitch_deg": 0.0,
  "fov_deg": 60.0,
  "output_size": {
    "w": 2689,
    "h": 2509
  }
}
```

### rectify

```json
{
  "enabled": true,
  "source": "hardcoded",
  "alpha": 0.0,
  "output_size": {
    "w": 2689,
    "h": 2509
  },
  "resized": false
}
```

### stitch

```json
{
  "ok": false,
  "good": 8,
  "inliers": 0,
  "model": "affine",
  "reuse_prev": false
}
```

### yolo

```json
{
  "run": true,
  "image_size": {
    "w": 2689,
    "h": 2509
  },
  "backend": "cpu",
  "count": 0,
  "detections": [],
  "state": {
    "ok": true,
    "backend": "cpu",
    "conf_used": 0.25,
    "nms_used": 0.45,
    "input_size": 608,
    "reason": "ok"
  },
  "vis_path": "/srv/static-persister/segdete/0225081901.Segdete.1/2026-04-14/saved_images/stitched_det_172356.png"
}
```