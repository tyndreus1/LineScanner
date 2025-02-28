import sys
import cv2
import numpy as np
import mvsdk
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QPushButton, QSlider, QHBoxLayout
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QTimer, Qt

class LineScanCameraApp(QWidget):
    def __init__(self):
        super().__init__()

        # GUI Setup
        self.setWindowTitle("Line Scan Camera Viewer")
        self.setGeometry(100, 100, 1600, 1400)

        # Create image display
        self.image_label = QLabel(self)
        self.image_label.setStyleSheet("border: 1px solid black;")

        # Create buttons
        self.start_button = QPushButton("Start Capture", self)
        self.start_button.clicked.connect(self.start_capture)

        self.stop_button = QPushButton("Stop Capture", self)
        self.stop_button.clicked.connect(self.stop_capture)
        self.stop_button.setEnabled(False)

        # Exposure slider
        #self.exposure_slider = QSlider(Qt.Horizontal)
        #self.exposure_slider.setMinimum(1000)  
        #self.exposure_slider.setMaximum(50000)  
        #self.exposure_slider.setValue(1000)  
        #self.exposure_slider.setTickInterval(5000)
        #self.exposure_slider.setTickPosition(QSlider.TicksBelow)
        #self.exposure_slider.valueChanged.connect(self.set_exposure)
        
        # Analog Gain slider
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setMinimum(1)  
        self.gain_slider.setMaximum(32)  
        self.gain_slider.setValue(20)  
        self.gain_slider.setTickInterval(1)
        self.gain_slider.setTickPosition(QSlider.TicksBelow)
        self.gain_slider.valueChanged.connect(self.set_analog_gain)
        
        
        

        # Layouts
        main_layout = QHBoxLayout()
        control_layout = QVBoxLayout()

        #control_layout.addWidget(QLabel("Exposure (µs):"))
        #control_layout.addWidget(self.exposure_slider)
        control_layout.addWidget(QLabel("Analog Gain (1x-16x):"))
        control_layout.addWidget(self.gain_slider)
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)

        # Image & Controls
        main_layout.addWidget(self.image_label, 3)
        main_layout.addLayout(control_layout, 1)
        self.setLayout(main_layout)

        # Camera Variables
        self.hCamera = None
        self.cap = None
        self.monoCamera = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.rows = []

        # Line Rate Calculation (from 5mm/s movement & 7um pixel size)
        self.line_rate_hz = 100
        self.timer_interval_ms = int(1000 / self.line_rate_hz)  

    def initialize_camera(self):
        """Initialize the camera."""
        DevList = mvsdk.CameraEnumerateDevice()
        if len(DevList) < 1:
            print("No camera found!")
            return None, None, None

        DevInfo = DevList[0]  
        try:
            hCamera = mvsdk.CameraInit(DevInfo, -1, -1)
        except mvsdk.CameraException as e:
            print(f"CameraInit Failed({e.error_code}): {e.message}")
            return None, None, None

        cap = mvsdk.CameraGetCapability(hCamera)
        monoCamera = cap.sIspCapacity.bMonoSensor != 0
        pixel_format = mvsdk.CAMERA_MEDIA_TYPE_MONO8 if monoCamera else mvsdk.CAMERA_MEDIA_TYPE_BGR8
        mvsdk.CameraSetIspOutFormat(hCamera, pixel_format)

        mvsdk.CameraSetTriggerMode(hCamera, 0)
        mvsdk.CameraSetAeState(hCamera, 0)
        #mvsdk.CameraSetExposureTime(hCamera, self.exposure_slider.value())
        mvsdk.CameraSetExposureTime(hCamera, 500)
        mvsdk.CameraPlay(hCamera)

        return hCamera, cap, monoCamera

    #def set_exposure(self):
        """Update camera exposure time."""
        #if self.hCamera:
        #    exposure_time = self.exposure_slider.value()
        #    mvsdk.CameraSetExposureTime(self.hCamera, exposure_time)
        #    print(f"Exposure set to: {exposure_time} µs")
    
    def set_analog_gain(self):
        """Update analog gain."""
        if self.hCamera:
            gain_value = self.gain_slider.value()
            mvsdk.CameraSetAnalogGain(self.hCamera, gain_value)
            print(f"Analog Gain set to: {gain_value}x")        
            
            

    def start_capture(self):
        """Starts the capture process."""
        if self.hCamera is None:
            self.hCamera, self.cap, self.monoCamera = self.initialize_camera()
            if self.hCamera is None:
                return

        self.rows = []  
        self.timer.start(self.timer_interval_ms)  
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        print("Capture started...")

    def update_frame(self):
        """Fetches new scan lines and updates the GUI."""
        if not self.hCamera:
            return

        try:
            pRawData, FrameHead = mvsdk.CameraGetImageBuffer(self.hCamera, 200)
            pFrameBuffer = mvsdk.CameraAlignMalloc(FrameHead.uBytes, 16)
            mvsdk.CameraImageProcess(self.hCamera, pRawData, pFrameBuffer, FrameHead)
            mvsdk.CameraReleaseImageBuffer(self.hCamera, pRawData)

            frame_data = (mvsdk.c_ubyte * FrameHead.uBytes).from_address(pFrameBuffer)
            frame = np.frombuffer(frame_data, dtype=np.uint8)

            actual_width, actual_height = FrameHead.iWidth, FrameHead.iHeight
            expected_size = actual_width * actual_height

            # **Fix Incorrect Frame Size Issue**
            if FrameHead.uBytes == expected_size * 3:  # 12-bit packed or RGB
                print("Detected RGB image, converting to grayscale...")
                frame = frame.reshape((actual_height, actual_width, 3))
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            elif FrameHead.uBytes == expected_size:  
                frame = frame.reshape((actual_height, actual_width))
            else:
                print(f"Unexpected frame size {FrameHead.uBytes}, skipping...")
                return

            # Resize to 4096x4 if needed
            if actual_width != 4096 or actual_height != 4:
                frame = cv2.resize(frame, (4096, 4), interpolation=cv2.INTER_NEAREST)

            self.rows.insert(0, frame)  # Inserts each new scan line at the top (reversing the order)
            self.update_gui_display()

            mvsdk.CameraAlignFree(pFrameBuffer)

        except mvsdk.CameraException as e:
            print(f"Camera Error: {e.message}")

    def update_gui_display(self):
        """Updates the PyQt GUI with the new image."""
        if not self.rows:
            return

        full_image = np.vstack(self.rows)
        full_image = cv2.resize(full_image, (1200, 1200), interpolation=cv2.INTER_NEAREST)

        height, width = full_image.shape
        bytes_per_line = width
        q_img = QImage(full_image.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(q_img)

        self.image_label.setPixmap(pixmap)

    def stop_capture(self):
        """Stops the camera and saves the image."""
        self.timer.stop()
        if self.rows:
            final_image = np.vstack(self.rows)
            cv2.imwrite("scanned_image.png", final_image)
            print("Image saved as scanned_image.png")

        if self.hCamera:
            mvsdk.CameraUnInit(self.hCamera)
            self.hCamera = None

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        print("Capture stopped.")

def main():
    app = QApplication(sys.argv)
    window = LineScanCameraApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
