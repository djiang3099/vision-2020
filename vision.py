# pylint: disable=C0330
# pylint: disable=E1101

"""The Drop Bears' 2020 vision code.

This code is run on the Raspberry Pi 4. It is uploaded via the browser interface.
It can be found at https://github.com/thedropbears/vision-2020
"""
import sys
import cv2
import numpy as np
from connection import Connection
from camera_manager import CameraManager
from magic_numbers import *
from utilities.functions import *
import math
import time


class Vision:
    """Main vision class.

    An instance should be created, with test=False (default). As long as the cameras are configured
    correctly via the GUI interface, everything will work without modification required.
    This will not work on most machines, so tests of the main process function are
    the only tests that can be done without a Pi running the FRC vision image.
    """

    entries = None

    def __init__(
        self, test_img=[], test_video=[], test_display=False, using_nt=False,
    ):
        # self.entries = entries
        # Memory Allocation
        self.hsv = np.zeros(shape=(FRAME_WIDTH, FRAME_HEIGHT, 3), dtype=np.uint8)
        self.image = self.hsv.copy()
        self.mask = np.zeros(shape=(FRAME_WIDTH, FRAME_HEIGHT), dtype=np.uint8)

        # Camera Configuration
        self.CameraManager = CameraManager(
            test_img=test_img, test_video=test_video, test_display=test_display
        )
        self.testing = len(test_video) or len(test_img)
        if not self.testing:
            self.CameraManager.setCameraProperty(0, "white_balance_temperature_auto", 0)
            self.CameraManager.setCameraProperty(0, "exposure_auto", 1)
            self.CameraManager.setCameraProperty(0, "focus_auto", 0)
            self.CameraManager.setCameraProperty(0, "exposure_absolute", 1)

        self.Connection = Connection(using_nt=using_nt, test=self.testing)

    def find_loading_bay(self, frame: np.ndarray):
        cnts, hierarchy = cv2.findContours(
            self.mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )
        cnts = np.array(cnts)
        hierarchy = np.array(hierarchy)[0]
        outer_rects = {}
        inner_rects = {}

        for i, cnt in enumerate(cnts):
            if hierarchy[i][3] == -1:
                outer_rects[i] = (
                    get_corners_from_contour(cnt),
                    hierarchy[i],
                    cv2.contourArea(cnt),
                )
            else:
                inner_rects[i] = (
                    get_corners_from_contour(cnt),
                    hierarchy[i],
                    cv2.contourArea(cnt),
                )
        if not (inner_rects and outer_rects):
            return None

        good = []

        for i in outer_rects:
            if outer_rects[i][2] > MIN_CONTOUR_AREA:
                current_inners = []
                next_child = outer_rects[i][1][2]
                while next_child != -1:
                    current_inners.append(inner_rects[next_child])
                    next_child = inner_rects[next_child][1][0]
                largest = max(current_inners, key=lambda x: x[2])
                if (
                    abs((outer_rects[i][2] / largest[2]) - LOADING_INNER_OUTER_RATIO)
                    < 0.5
                    and abs(
                        (cv2.contourArea(outer_rects[i][0]) / outer_rects[i][2]) - 1
                    )
                    < LOADING_RECT_AREA_RATIO
                    and abs((cv2.contourArea(largest[0]) / largest[2]) - 1)
                    < LOADING_RECT_AREA_RATIO
                ):
                    good.append((outer_rects[i], largest))

        self.image = frame.copy()
        for pair in good:
            self.image = cv2.drawContours(
                self.image, pair[0][0].reshape((1, 4, 2)), -1, (255, 0, 0), thickness=2
            )
            self.image = cv2.drawContours(
                self.image,
                pair[1][0].reshape((1, 4, 2)),
                -1,
                (255, 0, 255),
                thickness=1,
            )
        return (0.0, 0.0)

    def find_power_port(self, frame: np.ndarray) -> tuple:
        _, cnts, _ = cv2.findContours(frame, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if len(cnts) >= 1:
            acceptable_cnts = []
            for current_contour in enumerate(cnts):
                area = cv2.contourArea(current_contour[1])
                box = cv2.boundingRect(current_contour[1])
                hull_area = cv2.contourArea(cv2.convexHull(current_contour[1]))
                if (
                    area > MIN_CONTOUR_AREA
                    and area / hull_area > POWER_PORT_AREA_RATIO
                    and box[2] > box[3]
                ):
                    acceptable_cnts.append(current_contour[1])

            if acceptable_cnts:
                power_port_contour = max(
                    acceptable_cnts, key=lambda x: cv2.contourArea(x)
                )
                power_port_points = get_corners_from_contour(power_port_contour)
                # x, y, w, h = cv2.boundingRect(power_port_contour)
                return power_port_points
            else:
                return None
        else:
            return None

    def create_annotated_display(
        self, frame: np.ndarray, points: np.ndarray, printing=False
    ):
        for i in range(len(points)):
            cv2.circle(frame, (points[i][0][0], points[i][0][1]), 5, (0, 255, 0))
        if printing == True:
            print(points)

    def get_middles(self, contour: np.ndarray) -> tuple:
        """ Use the cv2 moments to find the centre x of the contour.
        We just copied it from the opencv reference. The y is just the lowest
        pixel in the image."""
        M = cv2.moments(contour)
        if M["m00"] != 0:
            cX = int(M["m10"] / M["m00"])
        else:
            cX = 160
        cY = max(list(contour[:, :, 1]))
        return cX, cY

    def get_image_values(self, frame: np.ndarray) -> tuple:
        """Takes a frame, returns a tuple of results, or None."""
        self.hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV, dst=self.hsv)
        self.mask = cv2.inRange(
            self.hsv, HSV_LOWER_BOUND, HSV_UPPER_BOUND, dst=self.mask
        )
        # self.mask = cv2.erode(self.mask, None, dst=self.mask, iterations=1)
        # self.mask = cv2.dilate(self.mask, None, dst=self.mask, iterations=2)
        # self.mask = cv2.erode(self.mask, None, dst=self.mask, iterations=1)

        power_port = self.find_power_port(self.mask)
        self.image = self.mask

        if power_port is not None:
            self.create_annotated_display(frame, power_port)
            midX, midY = self.get_middles(power_port)
            # box_height = cv2.boundingRect(power_port)[3] # using this could make it more reliable
            angle = get_horizontal_angle(midX, INTR_MATRIX)
            vert_angle = get_vertical_angle(midY, INTR_MATRIX)
            distance = get_distance(
                vert_angle, TARGET_HEIGHT, CAMERA_HEIGHT, GROUND_ANGLE
            )
            print(distance)
            return (distance, angle)
        else:
            return None

    def run(self):

        """Main process function.
        When ran, takes image, processes image, and sends results to RIO.
        """
        if not self.testing:
            if self.Connection.using_nt:
                self.Connection.pong()
        frame_time, self.frame = self.CameraManager.get_frame(0)
        if frame_time == 0:
            print(self.CameraManager.sinks[0].getError(), file=sys.stderr)
            self.CameraManager.source.notifyError(
                self.CameraManager.sinks[0].getError()
            )
        else:
            self.frame = cv2.rotate(self.frame, cv2.ROTATE_180)
            results = self.get_image_values(self.frame)
            if results is not None:
                distance, angle = results
                self.Connection.send_results(
                    (distance, angle, time.monotonic())
                )  # distance (meters), angle (radians), timestamp
            self.CameraManager.send_frame(self.image)


if __name__ == "__main__":
    sampleImgs = True
    # These imports are here so that one does not have to install cscore
    # (a somewhat difficult project on Windows) to run tests.
    if sampleImgs:
        import os

        testImgs = os.listdir("tests/power_port/")

        for im in testImgs:
            print(im.split("m")[0] + "\t", end="")
            camera_server = Vision(
                test_img=cv2.imread("tests/power_port/" + im), test_display=True
            )
            camera_server.run()
    else:
        camera_server = Vision(using_nt=True)
        while True:
            camera_server.run()
