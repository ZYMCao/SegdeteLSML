# SegDete

SegDete monitors paved surfaces by turning camera captures into classified and annotated inspection results.

## Language

**Camera replay**:
A test acquisition mode in which a recorded field image is presented to a running SegDete service as a new camera capture.
_Avoid_: Offline test, serial camera, replay processor

**Replay producer**:
A tool that submits recorded field images for camera replay without performing inspection itself.
_Avoid_: Virtual camera service, detector

**Inspection service**:
The single owner of capture processing and result publication, regardless of whether a capture is physical or replayed.
_Avoid_: Replay script, uploader
