import time
from machine import Timer, RTC
import machine
import binascii
import network
import pycom
from network import LTE


from sensors import ds1820, hx711, bme280
import logger
import webserver
from wlanmanager import WLanManager

from config import Config

boottime = Timer.Chrono()
boottime.start()

_config = Config()

_wlan = network.WLAN(id=0)
lte = LTE()

_ds_positions = {v: k for k, v in
                 _config.get_value('sensors', 'ds1820', 'positions').items()}

_wm = WLanManager()

reset_causes = {
    machine.PWRON_RESET: 'PWRON',  # Press reset button on FiPy
    machine.HARD_RESET: 'HARD',
    machine.WDT_RESET: 'WDT',  # Upload and restart from USB or machine.reset()
    machine.DEEPSLEEP_RESET: 'DEEPSLEEP',
    machine.SOFT_RESET: 'SOFT',
    machine.BROWN_OUT_RESET: 'BROWN_OUT'
}

measurement_interval = _config.get_value('general', 'general', 'measurement_interval')


def start_measurement():
    AP_TIME = 2 * 60
    perf = Timer.Chrono()
    pycom.heartbeat(False)
    pycom.rgbled(0x000000)

    perf.start()

    while boottime.read() < AP_TIME:
        # Measure all enabled sensors
        data = {}
        if ds1820 is not None:
            for rom in ds1820.roms:
                ds1820.start_conversion(rom=rom)
            time.sleep_ms(750)
            for rom in ds1820.roms:
                try:
                    ds_measurement = ds1820.read_temp_async(rom=rom)
                    ds_name = binascii.hexlify(rom).decode('utf-8')
                    if ds_name in _ds_positions:
                        data[_ds_positions[ds_name]] = ds_measurement
                except Exception as e:
                    log("Did not find rom" + str(e))
        if bme280 is not None:
            try:
                (data['t'],
                 data['p'],
                 data['h']) = bme280.read_compensated_data()

                data['p'] = data['p'] / 100  # Pa to mBar
            except Exception:
                log("BME280 not measuring.")
        if hx711 is not None:
            data['weight_kg'] = hx711.get_value(times=5)

        # Log measured values
        perf.start()
        if _csv is not None:
            _csv.add_dict(data)
        if _wlan.mode() == network.WLAN.STA and _wlan.isconnected() and _beep is not None:
            log("beep")
            _beep.add(data)
        log(data)
        perf.stop()
        time_elapsed = perf.read()
        perf.reset()
        time_until_measurement = measurement_interval - time_elapsed
        log('SecondsO elapsed: {:.2f}s, time until next measurement: {:.2f}s'.format(time_elapsed, time_until_measurement))

        # 10 Minuten nach dem Strom an soll der AC da sein.
        log('boottime: ' + str(boottime.read()))
        if machine.reset_cause() != machine.DEEPSLEEP_RESET and boottime.read() < AP_TIME:
            log('sleep')
            time.sleep_ms(int(abs(time_until_measurement) * 1000))
        else:
            lte.dettach()
            _wlan.deinit()
            log('deepsleep')
            # machine.deepsleep(int(abs(time_until_measurement * 1000)))
            machine.deepsleep(int(abs(10 * 1000)))

    log('Unexpected exited while loop')
    machine.reset()


def log(message):
    if _csv is not None:
        _csv.log(message)
    else:
        print(message)


def enable_ap(pin=None):
    global _wm, _wlan
    log("Called. Pin {}.".format(pin))
    if not _wlan.mode == network.WLAN.AP:
        log("enabled ap")
        pycom.heartbeat(False)
        pycom.rgbled(0x111100)
        getattr(_wm, 'enable_ap')()
    if not webserver.mws.IsStarted():
        webserver.mws.Start(threaded=True)


if _config.get_value('general', 'general', 'button_ap_enabled'):
    button_ap = machine.Pin(_config.get_value('general', 'general', 'button_ap_pin'),
                            mode=machine.Pin.IN,
                            pull=machine.Pin.PULL_UP)
    button_ap.callback(machine.Pin.IRQ_RISING,
                       handler=enable_ap)


try:
    rtc = RTC()
    rtc.init(time.gmtime(_config.get_value('general', 'general', 'initial_time')))

    _csv = logger.csv

    log("Starting from: {}".format(reset_causes[machine.reset_cause()]))

    if _config.get_value('networking', 'wlan', 'enabled'):
        _wm.enable_client()
        _beep = logger.beep
        if _wlan.mode() == network.WLAN.STA and _wlan.isconnected():
            try:
                log("Pre Time: " + str(rtc.now()))
                rtc.ntp_sync("pool.ntp.org")
                log("Time: " + str(rtc.now()))
            except Exception as e:
                log(str(e))

    if machine.reset_cause() != machine.DEEPSLEEP_RESET:
        log("Start AP")
        # _thread.start_new_thread(enable_ap, ())
        enable_ap()

    log(boottime.read())
    start_measurement()

    # _wlan.deinit()
except Exception as e:
    log("Exception: " + str(e))
finally:
    machine.reset()
