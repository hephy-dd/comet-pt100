"""Pt100

COMET application measuring temperature ramps with CTS climate chamber and
Keitley 2700 multimeter using a Pt100 temperature sensor.

"""
import time
import logging
from PyQt5 import QtCore

import comet
from comet.mixins import ResourceMixin

from comet.devices.cts import ITC
from comet.devices.keithley import K2700

class MeasureProcess(comet.Process, ResourceMixin):
    """Measurement process."""

    reading = QtCore.pyqtSignal(object)
    """Signal is emitted if new reading available."""

    poll_interval = 10

    offset = .5

    def run(self):
        with ITC(self.resources.get("cts")) as cts, \
             K2700(self.resources.get("multi")) as multi:
            # CTS ON
            cts.query_bytes("s1 1", 2)
            self.measure(cts, multi)
            # CTS OFF
            cts.query_bytes("s1 0", 2)

    def read(self, cts, multi):
        # Get CTS
        t = time.time()
        temp = (t, cts.analogChannel(1)[0])
        humid = (t, cts.analogChannel(2)[0])
        # Measure
        multi.init()
        pt100 = (t, multi.fetch()[0].get('_C', -100))
        reading = dict(
            temp=temp,
            humid=humid,
            pt100=pt100
        )
        self.reading.emit(reading)
        return reading

    def measure(self, cts, multi):
        reading = self.read(cts, multi)
        ramps = comet.get("table").data
        # Loop over temperature ramps
        for ramp in ramps:
            current_temp = reading.get('temp')[1]
            end_temp = ramp.get('end')
            step_temp = ramp.get('step')
            if end_temp < current_temp:
                step_temp = -step_temp
            # Ramp
            for target_temp in comet.Range(current_temp, end_temp, step_temp):
                # cts.setAnalogChannel(1, target_temp) # BUG
                cts.query_bytes("a{} {:05.1f}".format(0, target_temp), 1)
                # Wait until target temperature reached
                while not target_temp - self.offset < current_temp < target_temp + self.offset:
                    logging.info("target: {}, current: {}".format(target_temp, current_temp))
                    reading = self.read(cts, multi)
                    current_temp = reading.get('temp')[1]
                    # Exit on stop request
                    if self.stopRequested():
                        return
                    time.sleep(self.poll_interval)
                # Wait until interval elapsed
                time_end = time.time() + ramp.get('interval')
                while time.time() < time_end:
                    self.read(cts, multi)
                    # Exit on stop request
                    if self.stopRequested():
                        return
                    time.sleep(self.poll_interval)

def on_add_ramp(event):
    """Add ramp to table."""
    end = comet.get("ramp_end").value
    step = comet.get("ramp_step").value
    interval = comet.get("ramp_interval").value
    comet.get("table").append(end=end, step=step, interval=interval)

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

def on_failed(exception):
    """On measurement failed."""
    comet.get("root").qt.showException(exception)

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
    measure.failed.connect(on_failed)
    measure.reading.connect(on_update)
    app.processes().add("measure", measure)

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
                title="Add Temp. Ramp",
                layout=comet.Column(
                    comet.Label(text="Target Temp."),
                    comet.Number(id="ramp_end", value=25, minimum=-40, maximum=120, unit="°C"),
                    comet.Label(text="Step"),
                    comet.Number(id="ramp_step", value=5, maximum=25, unit="°C"),
                    comet.Label(text="Duration"),
                    comet.Number(id="ramp_interval", value=1, maximum=60, precision=1, unit="min"),
                    comet.Button(title="Add", click=on_add_ramp)
                )
            ),
            comet.FieldSet(
                id="ramps_fs",
                title="Temp. Ramps",
                layout=comet.Column(
                    comet.Table(
                        id="table",
                        columns=["end", "step", "interval"],
                        titles=dict(end="Target °C", step="Step in °C", interval="Dur. min")
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
