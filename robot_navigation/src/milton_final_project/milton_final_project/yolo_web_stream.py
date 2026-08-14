from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


class YoloWebStream(Node):
    def __init__(self):
        super().__init__('yolo_web_stream')

        self.declare_parameter('image_topic', '/yolo/annotated_image')
        self.declare_parameter('host', '0.0.0.0')
        self.declare_parameter('port', 8080)

        self.bridge = CvBridge()
        self.frame_lock = Lock()
        self.latest_jpeg = None

        image_topic = self.get_parameter('image_topic').value
        host = self.get_parameter('host').value
        port = self.get_parameter('port').value

        self.create_subscription(
            Image,
            image_topic,
            self.image_callback,
            qos_profile_sensor_data,
        )

        handler = self.make_handler()
        self.server = ThreadingHTTPServer((host, port), handler)
        self.server_thread = Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

        self.get_logger().info(f'Streaming {image_topic} at http://{host}:{port}')

    def image_callback(self, msg):
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return

        with self.frame_lock:
            self.latest_jpeg = jpeg.tobytes()

    def make_handler(self):
        node = self

        class StreamHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                if self.path in ('/', '/index.html'):
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.end_headers()
                    self.wfile.write(
                        b'<html><head><title>YOLO Stream</title></head>'
                        b'<body style="margin:0;background:#111;color:white;'
                        b'font-family:sans-serif;text-align:center">'
                        b'<h2>YOLO Annotated Stream</h2>'
                        b'<img src="/stream.mjpg" style="max-width:100%;height:auto">'
                        b'</body></html>'
                    )
                    return

                if self.path != '/stream.mjpg':
                    self.send_error(404)
                    return

                self.send_response(200)
                self.send_header('Age', '0')
                self.send_header('Cache-Control', 'no-cache, private')
                self.send_header('Pragma', 'no-cache')
                self.send_header(
                    'Content-Type',
                    'multipart/x-mixed-replace; boundary=frame',
                )
                self.end_headers()

                while rclpy.ok():
                    with node.frame_lock:
                        frame = node.latest_jpeg

                    if frame is None:
                        continue

                    try:
                        self.wfile.write(b'--frame\r\n')
                        self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                    except BrokenPipeError:
                        break

        return StreamHandler

    def destroy_node(self):
        self.server.shutdown()
        self.server.server_close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = YoloWebStream()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
