"""Pt100

COMET application measuring temperature ramps with CTS climate chamber and
Keitley 2700 multimeter using a Pt100 temperature sensor.

"""
import time
import datetime
import logging
import csv
import re
import os

from PyQt5 import QtCore

import comet
from comet.mixins import ResourceMixin

from comet.devices.cts import ITC
from comet.devices.keithley import K2700

def iso_datetime():
    """Returns filesystem safe ISO date time."""
    return datetime.datetime.now().replace(microsecond=0).isoformat().replace(':', '-')

class ITC(ITC):
    """Extended ITC device."""

    def start(self):
        """Switch climate chamber ON."""
        result = self.query_bytes("s1 1", 2)
        if result != "s1":
            raise RuntimeError("Failed to start")

    def stop(self):
        """Switch climate chamber OFF."""
        result = self.query_bytes("s1 0", 2)
        if result != "s1":
            raise RuntimeError("Failed to stop")

class K2700(K2700):
    """Extended K2700 device."""

    def fetch(self):
        """Returns the latest available readings as list of dictionaries.
        .. note:: It does not perform a measurement.
        >>> device.fetch()
        [{'VDC': -4.32962079e-05, 'SECS': 0.0, 'RDNG': 0.0}, ...]
        """
        results = []
        # split '-4.32962079E-05VDC,+0.000SECS,+0.0000RDNG#,...' into list of dicts
        for values in re.findall(r'([^#]+)#\,?', self.resource().query('FETC?')):
            values = re.findall(r'([+-]?\d+(?:\.\d+)?(?:[eE][+-]\d+)?)([_A-Z]+)\,?', values)
            results.append({suffix: float(value) for value, suffix in values})
        return results

class MeasureProcess(comet.Process, ResourceMixin):
    """Measurement process."""

    reading = QtCore.pyqtSignal(object)
    """Signal is emitted if new reading available."""

    poll_interval = 10

    offset = .1

    def run(self):
        self.filename = os.path.join(os.path.expanduser('~'), 'pt100-{}.csv'.format(iso_datetime()))
        cts_resource = self.resources.get("cts")
        multi_resource = self.resources.get("multi")
        with ITC(cts_resource) as cts, K2700(multi_resource) as multi:
            cts.start()
            self.measure(cts, multi)
            self.hideProgress()
            cts.stop()

    def read(self, cts, multi):
        # Get CTS
        t = time.time()
        temp = cts.analogChannel(1)[0]
        humid =cts.analogChannel(2)[0]
        # Measure
        multi.init()
        pt100 = multi.fetch()[0].get('_C', 0)
        logging.info('K2700: %s degC', pt100)
        reading = dict(
            temp=(t, temp),
            humid=(t, humid),
            pt100=(t, pt100)
        )
        self.reading.emit(reading)
        with open(self.filename, 'a', newline='') as fp:
            writer = csv.writer(fp)
            writer.writerow([t, temp, humid, pt100])
        return reading

    def measure(self, cts, multi):
        # Setup CSV dump
        with open(self.filename, 'a', newline='') as fp:
            writer = csv.writer(fp)
            writer.writerow('time cts_temp cts_humid pt100'.split())

        # Initial reading
        reading = self.read(cts, multi)
        ramps = comet.get("table").data

        # Loop over temperature ramps
        for i, ramp in enumerate(ramps):
            self.showProgress(i + 1, len(ramps))
            current_temp = reading.get('temp')[1]
            end_temp = ramp.get('end')
            cts.setAnalogChannel(1, end_temp)
            # Wait until target temperature reached
            while not (end_temp - self.offset) <= current_temp <= (end_temp + self.offset):
                self.showMessage("Target temp. {} degC...".format(end_temp))
                logging.info("target: {}+-{}, current: {}".format(end_temp, self.offset, current_temp))
                reading = self.read(cts, multi)
                current_temp = reading.get('temp')[1]
                # Exit on stop request
                if self.stopRequested():
                    return
                time.sleep(self.poll_interval)
            # Wait until interval elapsed
            time_end = time.time() + ramp.get('interval') * 60
            while time.time() < time_end:
                self.showMessage("Waiting...")
                self.read(cts, multi)
                # Exit on stop request
                if self.stopRequested():
                    return
                time.sleep(self.poll_interval)

def on_add_ramp(event):
    """Add ramp to table."""
    end = comet.get("ramp_end").value
    interval = comet.get("ramp_interval").value
    comet.get("table").append(end=end, interval=interval)

def on_clear_ramps(event):
    """Clear ramp table."""
    comet.get("table").clear()

def on_started():
    """On measurement started."""
    comet.get("plot").clear()
    comet.get("start").enabled = False
    comet.get("stop").enabled = True
    comet.get("add_ramp_fs").enabled = False
    comet.get("ramps_fs").enabled = False

def on_finished():
    """On measurement finished."""
    comet.get("start").enabled = True
    comet.get("stop").enabled = False
    comet.get("add_ramp_fs").enabled = True
    comet.get("ramps_fs").enabled = True

def on_update(data):
    """On measurement reading."""
    comet.get("plot").append("pt100", data.get('pt100'))
    comet.get("plot").append("humid", data.get('humid'))
    comet.get("plot").append("temp", data.get('temp'))
    comet.get("plot").auto()

def main():
    app = comet.Application(name="comet-pt100")
    app.title = "Pt100"

    # Resources
    resources = QtCore.QSettings().value('resources', {})
    app.resources.update({
        "cts": resources.get("cts", "TCPIP::127.0.0.1::1080::SOCKET"),
        "multi": resources.get("multi", "TCPIP::127.0.0.1::10001::SOCKET")
    })

    # Processes
    measure = MeasureProcess()
    measure.started.connect(on_started)
    measure.finished.connect(on_finished)
    measure.reading.connect(on_update)
    app.processes().add("measure", measure)
    # Connect process with main window (tweak)
    app.get('root').qt.connectProcess(measure)

    # Layout
    app.layout = comet.Row(
        comet.Column(
            comet.FieldSet(
                title="Control",
                layout=comet.Column(
                    comet.Button(id="start", title="Start", click=lambda e: measure.start()),
                    comet.Button(id="stop", title="Stop", enabled=False, click=lambda e: measure.stop())
                )
            ),
            comet.FieldSet(
                id="add_ramp_fs",
                title="Add Temperature",
                layout=comet.Column(
                    comet.Label(text="Target Temp."),
                    comet.Number(id="ramp_end", value=25, minimum=-40, maximum=120, unit="°C"),
                    comet.Label(text="Duration"),
                    comet.Number(id="ramp_interval", value=1, maximum=3600, precision=1, unit="min"),
                    comet.Button(title="Add", click=on_add_ramp)
                )
            ),
            comet.FieldSet(
                id="ramps_fs",
                title="Temp. Ramps",
                layout=comet.Column(
                    comet.Table(
                        id="table",
                        columns=["end", "interval"],
                        titles=dict(end="Target °C", interval="Dur. min")
                    ),
                    comet.Button(title="Clear", click=on_clear_ramps)
                )
            ),
            comet.Stretch()
        ),
        comet.Plot(
            id="plot",
            axes=dict(
                x=dict(align="bottom", type="datetime", title="Time"),
                y=dict(align="left", type="value", title="Temp/Humid"),
            ),
            series=[
                dict(name="temp", x="x", y="y", title="CTS Temp."),
                dict(name="humid", x="x", y="y", title="CTS Humid"),
                dict(name="pt100", x="x", y="y", title="PT100")
            ]
        )
    )

    return app.run()

if __name__ == "__main__":
    sys.exit(main())
