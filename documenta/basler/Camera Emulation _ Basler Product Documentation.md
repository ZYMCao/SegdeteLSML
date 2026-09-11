Camera Emulation[\#](https://docs.baslerweb.com/camera-emulation#camera-emulation "Create link to this heading")

The Camera Emulation feature allows you to test basic camera features and create test images without having a physical camera device attached to your computer.

The camera emulation devices can be accessed using the pylon API and the pylon Viewer.

Overview[\#](https://docs.baslerweb.com/camera-emulation#overview "Create link to this heading")

In addition to camera transport layers like GigE Vision or USB3 Vision, pylon offers a transport layer that can create simple camera emulation devices. This allows you to develop applications without the need for a physical camera. It is also useful if you want to develop a multi-camera application and don't have enough cameras at hand.

You can create up to 256 camera emulation devices.

Besides emulating image acquisition and [standard camera features](https://docs.baslerweb.com/camera-emulation#standard-camera-features) , camera emulation devices also offer features that a physical camera does not offer:

- You can [display custom test images](https://docs.baslerweb.com/camera-emulation#displaying-custom-test-images) , e.g., to optimize your image processing algorithms.
- You can [generate failed buffers](https://docs.baslerweb.com/camera-emulation#generating-failed-buffers) , e.g., to test your exception handling routines.

Enabling Camera Emulation[\#](https://docs.baslerweb.com/camera-emulation#enabling-camera-emulation "Create link to this heading")

You can enable camera emulation [in the pylon Viewer](https://docs.baslerweb.com/camera-emulation#enabling-camera-emulation-in-the-pylon-viewer) , [in the pylon API](https://docs.baslerweb.com/camera-emulation#enabling-camera-emulation-in-the-pylon-api) , or both.

### Installing Camera Emulation Support[\#](https://docs.baslerweb.com/camera-emulation#installing-camera-emulation-support "Create link to this heading")

- If you are using pylon for Linux, camera emulation support is installed by default.
  - If you chose the **Camera User** or **Developer** profile during installation, camera emulation support is installed by default.
  - If you chose the **Custom** profile during installation, camera emulation support is only installed if you selected the **Camera Emulation Support** option. If you haven't done that, run the installer again and select that option.

### Enabling Camera Emulation in the pylon Viewer[\#](https://docs.baslerweb.com/camera-emulation#enabling-camera-emulation-in-the-pylon-viewer "Create link to this heading")

To enable camera emulation in the pylon Viewer:

1. Make sure that camera emulation support is [installed](https://docs.baslerweb.com/camera-emulation#installing-camera-emulation-support) .
2. In the **Tools** menu of the pylon Viewer, click **Options**.
3. In the **Options** dialog, click **Camera Emulation**.
4. On the **Camera Emulation** page, enter the desired number of camera emulation devices and click **OK**. The emulation devices will be visible in the **Devices** pane after a short wait. They can be accessed using the pylon Viewer. If you also want to access the devices in the pylon API, follow the [instructions below](https://docs.baslerweb.com/camera-emulation#enabling-camera-emulation-in-the-pylon-api) .

Info

If the number of camera emulation devices is set to 0, the **Camera Emulation** node will not be shown in the **Devices** pane.

### Enabling Camera Emulation in the pylon API[\#](https://docs.baslerweb.com/camera-emulation#enabling-camera-emulation-in-the-pylon-api "Create link to this heading")

To enable camera emulation in the pylon API:1. Make sure that camera emulation support is [installed](https://docs.baslerweb.com/camera-emulation#installing-camera-emulation-support) .
2. Add a [system environment variable](https://docs.baslerweb.com/camera-emulation#external-links) named `PYLON_CAMEMU` and set its value to the desired number of emulation devices. **Example:** `PYLON_CAMEMU=2` This will provide two emulation devices. They can be accessed using the pylon API. If you also want to access the devices in the pylon Viewer, follow the [instructions above](https://docs.baslerweb.com/camera-emulation#enabling-camera-emulation-in-the-pylon-viewer) .

Info

If `PYLON_CAMEMU` is not set or set to 0, no emulation devices will be available.

Standard Camera Features[\#](https://docs.baslerweb.com/camera-emulation#standard-camera-features "Create link to this heading")

Camera emulation devices can emulate the following standard camera features:

- [Acquisition Frame Rate](https://docs.baslerweb.com/acquisition-frame-rate.html)
- [Acquisition Status](https://docs.baslerweb.com/acquisition-status.html)
- [Device Information Parameters](https://docs.baslerweb.com/device-information-parameters.html)
- [Exposure Mode](https://docs.baslerweb.com/exposure-mode.html)
- [Exposure Time](https://docs.baslerweb.com/exposure-time.html)
- [Gain](https://docs.baslerweb.com/gain.html)
- [Image ROI](https://docs.baslerweb.com/image-roi.html)
- [Pixel Format](https://docs.baslerweb.com/pixel-format.html)
- [Resulting Acquisition Frame Rate](https://docs.baslerweb.com/resulting-acquisition-frame-rate.html)
- [Test Images](https://docs.baslerweb.com/test-images.html)
- [Triggered Image Acquisition](https://docs.baslerweb.com/triggered-image-acquisition.html)

Additional Features[\#](https://docs.baslerweb.com/camera-emulation#additional-features "Create link to this heading")

The following features are **only** available on camera emulation devices and **not** on physical Basler cameras.

### Displaying Custom Test Images[\#](https://docs.baslerweb.com/camera-emulation#displaying-custom-test-images "Create link to this heading")

In addition to displaying standard [test images](https://docs.baslerweb.com/test-images.html) , camera emulation allows you to display custom test images that are loaded from disk.

Info

- On **Windows**, the following image file formats can be loaded: BMP, JPG, PNG, and TIF.
- On **Linux**, the following image file formats can be loaded: PNG and TIF.

To display a custom test image:

1. Set the `TestImageSelector` parameter to `Off`. This disables the use of standard test images.
2. Set the `ImageFileMode` parameter to `On`. This enables the use of custom test images.
   1. Place all test images to be displayed in a single directory. The directory must not contain any subdirectories.
   2. Provide the full path of the directory containing the files in the `ImageFilename` parameter. **Example:** c:\\images\\
3. Acquire at least one image to display the test image(s). If you want to display the image(s) in the pylon Viewer, click the single or continuous shot button on the toolbar.

#### Troubleshooting[\#](https://docs.baslerweb.com/camera-emulation#troubleshooting "Create link to this heading")

- If the custom test image isn't displayed, i.e., the image displayed is completely black, then pylon couldn't load the file. Check the file name or path provided in the `ImageFilename` parameter. If you provided a directory name, make sure that the directory doesn't contain any subdirectories.
- If the custom test image is displayed in monochrome, switch to a color [pixel format](https://docs.baslerweb.com/pixel-format.html) (BGR/BGRA/RGB).
- If the custom test image isn't displayed in full size, adjust the [image ROI](https://docs.baslerweb.com/image-roi.html) parameters (`Width`, `Height`, `OffsetX`, and `OffsetY`). If the image is bigger than 4096 x 4096: Before setting the `Width` and `Height` parameters, make sure that the `WidthMax` and `HeightMax` parameter values are adjusted to the correct maximum image size.### Generating Failed Buffers[\#](https://docs.baslerweb.com/camera-emulation#generating-failed-buffers "Create link to this heading")

The Force Failed Buffer feature allows you to simulate a bad camera connection by generating failed buffers. This can be useful, e.g., to test your exception handling routines.

To generate failed buffers:

1. Start image acquisition.
2. Set the `ForceFailedBufferCount` parameter to the number of failed buffers you want to generate.
3. Execute the `ForceFailedBuffer` command. The camera emulation device will now generate corrupt images. The number of corrupt images depends on the value of the `ForceFailedBufferCount` parameter.

External Links[\#](https://docs.baslerweb.com/camera-emulation#external-links "Create link to this heading")

- [How to set the path and environment variables in Windows (Computer Hope)](https://www.computerhope.com/issues/ch000549.htm)
- [HowTo: Set an Environment Variable in Linux (Dowd and Associates)](https://www.dowdandassociates.com/blog/content/howto-set-an-environment-variable-in-linux/)

Sample Code[\#](https://docs.baslerweb.com/camera-emulation#sample-code "Create link to this heading")

```python
# ** Custom Test Images **
# Disable standard test images
camera.TestImageSelector.Value = "Off"
# Enable custom test images
# camera.ImageFileMode.Value = "On"
# Load custom test image from disk
camera.ImageFileMode.Value = "On"
camera.ImageFilename.Value = "c:\\images\\image1.png"
# ** Force Failed Buffer **
# Set the number of failed buffers to generate to 40
camera.ForceFailedBufferCount.Value = 40
# Generate 40 failed buffers
camera.ForceFailedBuffer.Execute()
```

You can also [use the pylon Viewer](https://docs.baslerweb.com/configuring-camera-parameters.html) to easily set the parameters.

Was this page helpful?

Thanks for your feedback\!

Thanks for your feedback\! Help us improve this page by using our

Back to top