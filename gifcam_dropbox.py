#!/usr/bin/env python3
import os
import time
import random, string
from time import sleep
import socket
import logging
from logging.handlers import RotatingFileHandler, SysLogHandler

import RPi.GPIO as GPIO
from picamera2 import Picamera2
from libcamera import Transform
from twython import Twython

import dropbox
from dropbox.files import WriteMode, DropboxOAuth2FlowNoRedirect

########################
# Dropbox Setup
########################
DROPBOX_ACCESS_TOKEN  = 'ADD YOUR TOKEN HERE'
DROPBOX_TARGET_FOLDER = 'TARGET FOLDER LOCATION'

########################
# Behaviour Variables
########################
num_frame = 10       # Number of frames in GIF
gif_delay = 5        # Frame delay [ms]
rebound = False       # Create a looping video (start<=>end)
WIFI_CHECK_INTERVAL = 10  # seconds
_last_wifi_check = 0
gif_dir = '/home/pi/gifcam/gifs' # <- Make sure this is updated to where the GIFs are located

########################
# Configure Logging Setup
########################
logging.basicConfig(
    level=logging.INFO,  # adjust to DEBUG for more verbosity
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        # – File handler with rotation:
        RotatingFileHandler(
            "/home/joshua/gifcam/logs/gifcam.log",
            maxBytes=2_000_000,   # rotate after ~2 MB
            backupCount=3         # keep 3 old files
        ),
        # – (Optional) send logs to syslog/journald:
        SysLogHandler(address='/dev/log'),
        # – (Optional) still echo to console:
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("gifcam")
########################
# GPIO Setup
########################
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

shutter_button      = 19   # Shutter Button GPIO Pin
upload_button       = 17   # Dropbox upload button
button_led          = 12   # Processing‐status LED GPIO Pin
status_led          = 21   # Idle/ready LED GPIO Pin
wifi_status_led     = 16   # Wi-Fi status LED
dropbox_status_led  = 26   # Dropbox upload status LED

GPIO.setup(shutter_button, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(upload_button, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(button_led, GPIO.OUT)
GPIO.setup(status_led, GPIO.OUT)
GPIO.setup(wifi_status_led, GPIO.OUT)
GPIO.setup(dropbox_status_led, GPIO.OUT)

buttonLed = GPIO.PWM(button_led, 10)   # blinks during processing
statusLed = GPIO.PWM(status_led, 2)    # indicates idle vs busy
dropboxStatusLed = GPIO.PWM(dropbox_status_led, 10) # blinks during upload
GPIO.output(wifi_status_led, GPIO.LOW) # assumes no wifi until first check


########################
# Picamera2 Setup
########################
picam2 = Picamera2()
my_transform = Transform(90)
camera_config = picam2.create_still_configuration(
    main={"size": (540, 405)},
    transform=my_transform
)
picam2.configure(camera_config)
picam2.start()

# Start with “ready” indication
buttonLed.start(100)
statusLed.start(0)
dropboxStatusLed.start(0)

logger.info("System up and ready")

########################
# Wi-Fi Connectivity Check 
########################
def is_wifi_connected():
    """Quickly test Internet via DNS server."""
    try:
        logger.info("Testing for wifi connection.")
        socket.create_connection(("1.1.1.1", 53), timeout=2)
        logger.info("Successfully connected to the internet.")
        return True
    except OSError:
        logger.error("Failed to connect to the internet.")
        return False

########################
# Utility Methods
########################

def random_generator(size=10,
                     chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))

def blink_led_short(timesToBlink, targetLed):
    # Blink LED 3 times
    for _ in range(timesToBlink):
        GPIO.output(targetLed, GPIO.HIGH)  # Turn on
        time.sleep(0.2)                  # Wait 0.5 seconds
        GPIO.output(targetLed, GPIO.LOW)   # Turn off
        time.sleep(0.2)

def blink_led_long(timesToBlink, targetLed):
    # Blink LED 3 times
    for _ in range(timesToBlink):
        GPIO.output(targetLed, GPIO.HIGH)  # Turn on
        time.sleep(0.6)                  # Wait 0.5 seconds
        GPIO.output(targetLed, GPIO.LOW)   # Turn off
        time.sleep(0.6)

########################
# Dropbox Upload
########################
# ─────────────────────────────────────────
def upload_gifs(local_folder: str, dropbox_folder: str):
    dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)
    for fname in os.listdir(local_folder):
        if not fname.lower().endswith('.gif'):
            continue
        local_path = os.path.join(local_folder, fname)
        dropbox_path = f"{dropbox_folder}/{fname}"
        try:
            with open(local_path, 'rb') as f:
                dbx.files_upload(f.read(), dropbox_path, mode=WriteMode('overwrite'))
            logger.info(f"✔ Uploaded '{local_path}' → '{dropbox_path}'")
            logger.info('Upload complete')
        except Exception as e:
            logger.error(f"✘ Failed to upload '{local_path}': {e}")
# ─────────────────────────────────────────

try:
    while True:
        # ── update Wi‑Fi LED every 10 seconds ──
        now = time.time()
        if now - _last_wifi_check >= WIFI_CHECK_INTERVAL:
            connected = is_wifi_connected()
            GPIO.output(wifi_status_led, GPIO.HIGH if connected else GPIO.LOW)
            _last_wifi_check = now
        
        # --- Take a GIF --- #
        if GPIO.input(shutter_button) == GPIO.LOW:
            # Shutter Button pressed → make GIF
            logger.info('Gif Started')
            statusLed.ChangeDutyCycle(0)
            buttonLed.ChangeDutyCycle(50)

            rnd = random_generator()
            for i in range(num_frame):
                picam2.capture_file(f"{i:04d}.jpg")

            if rebound:
                for i in range(num_frame - 1):
                    src = f"{num_frame - i - 1:04d}.jpg"
                    dst = f"{num_frame + i:04d}.jpg"
                    os.system(f"cp {src} {dst}")

            statusLed.ChangeDutyCycle(50)
            buttonLed.ChangeDutyCycle(0)

            gif_dir = '/home/joshua/gifcam/gifs'
            os.makedirs(gif_dir, exist_ok=True)
            base = os.path.join(gif_dir, f"{rnd}-0")
            logger.info('Processing GIF…')
            os.system(f"gm convert -delay {gif_delay} *.jpg {base}.gif")
            os.system("rm ./*.jpg")

            logger.info('GIF complete')

            statusLed.ChangeDutyCycle(0)
            buttonLed.ChangeDutyCycle(100)
            logger.info('System Ready')
        
        # --- upload to Drobox --- #
        if GPIO.input(upload_button) == GPIO.LOW:
            if connected:
                GPIO.output(dropbox_status_led, GPIO.HIGH)
                logger.info('Uploading GIFs to Dropbox…')
                dropboxStatusLed.ChangeDutyCycle(75)
                statusLed.ChangeDutyCycle(25)
                upload_gifs(gif_dir, DROPBOX_TARGET_FOLDER)
                dropboxStatusLed.ChangeDutyCycle(0)
            else:
                logger.error('No wifi connection, aborting upload.')
                ### --- BLINK S.O.S. IN MORSE CODE --- ###
                blink_led_short(3, status_led)
                blink_led_long(3, status_led)
                blink_led_short(3, status_led)

        else:
            # Idle blink
            statusLed.ChangeDutyCycle(0)
            buttonLed.ChangeDutyCycle(100)
            sleep(0.05)

except KeyboardInterrupt:
    pass

finally:
    picam2.stop()
    picam2.close()
    GPIO.cleanup()
