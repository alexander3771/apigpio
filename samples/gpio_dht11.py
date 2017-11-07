import asyncio
from collections import namedtuple

import apigpio


class DHT11Result(namedtuple('DHT11Result', 'error_code temperature humidity')):
    ERR_NO_ERROR = 0
    ERR_MISSING_DATA = 1
    ERR_CRC = 2

    def __str__(self):
        return 'Temperature: {}°C, Humidity {} %'.format(self.temperature, self.humidity)

    def is_valid(self):
        return self.error_code == DHT11Result.ERR_NO_ERROR


class DHT11:
    """
    Async version of DHT11 class made by joan2937
    - https://github.com/joan2937/pigpio/blob/master/EXAMPLES/Python/DHT11_SENSOR/dht11.py

    example code:
    >>> address = ('192.168.1.10', 8888)
    >>> gpio = 4
    >>> async with apigpio.Pi(address) as pi:
    ....    async with DHT11(pi, gpio) as sensor:  # 4 is the data GPIO pin connected to your sensor
    ....        async for result in sensor:
    ....            if result.is_valid():
    ....                print(result)
    """

    def __init__(self, pi, gpio):
        """
        :type pi: apigpio.Pi
        :type gpio: int
        """
        self.temperature = self.humidity = 0
        self._pi = pi
        self._gpio = gpio
        self._high_tick = 0
        self._bit = 40
        self._either_edge_cb = None
        self._loop = asyncio.get_event_loop()
        self._error = DHT11Result.ERR_NO_ERROR

    async def connect(self):
        """
        Clears the internal gpio pull-up/down resistor.
        Kills any watchdogs.
        """
        await self._pi.set_pull_up_down(self._gpio, apigpio.PUD_OFF)
        await self._pi.set_watchdog(self._gpio, 0)
        await self.register_callbacks()

    async def register_callbacks(self):
        """
        Monitors RISING_EDGE changes using callback.
        """
        self._either_edge_cb = await self._pi.add_callback(
            self._gpio,
            apigpio.EITHER_EDGE,
            self.either_edge_callback
        )

    def either_edge_callback(self, gpio, level, tick):
        """
        Either Edge callbacks, called each time the gpio edge changes.
        Accumulate the 40 data bits from the dht11 sensor.
        """
        level_handlers = {
            apigpio.FALLING_EDGE: self._edge_FALL,
            apigpio.RISING_EDGE: self._edge_RISE,
            apigpio.EITHER_EDGE: self._edge_EITHER
        }
        handler = level_handlers[level]
        diff = apigpio.tick_diff(self._high_tick, tick)
        handler(tick, diff)

    def _edge_RISE(self, tick, diff):
        """
        Handle Rise signal.
        """
        val = 0
        if diff >= 50:
            val = 1
        if diff >= 200:  # Bad bit?
            self.checksum = 256  # Force bad checksum

        if self._bit >= 40:  # Message complete
            self._bit = 40

        elif self._bit >= 32:  # In checksum byte
            self.checksum = (self.checksum << 1) + val
            if self._bit == 39:
                # 40th bit received
                loop.create_task(self._pi.set_watchdog(self._gpio, 0))
                total = self.humidity + self.temperature
                # is checksum ok ?
                if not (total & 255) == self.checksum:
                    self._error = DHT11Result.ERR_CRC
                    return

        elif 16 <= self._bit < 24:  # in temperature byte
            self.temperature = (self.temperature << 1) + val
            self._error = DHT11Result.ERR_NO_ERROR

        elif 0 <= self._bit < 8:  # in humidity byte
            self.humidity = (self.humidity << 1) + val
            self._error = DHT11Result.ERR_NO_ERROR

        else:  # skip header bits
            pass

        self._bit += 1

    def _edge_FALL(self, tick, diff):
        """
        Handle Fall signal.
        """
        self._high_tick = tick
        if diff <= 250000:
            return
        self._bit = -2
        self.checksum = 0
        self.temperature = 0
        self.humidity = 0

    def _edge_EITHER(self, tick, diff):
        """
        Handle Either signal.
        """
        loop.create_task(self._pi.set_watchdog(self._gpio, 0))

    async def read(self):
        """
        Start reading over DHT11 sensor.
        """
        await self._pi.write(self._gpio, apigpio.LOW)
        await asyncio.sleep(0.017)  # 17 ms
        await self._pi.set_mode(self._gpio, apigpio.INPUT)
        await self._pi.set_watchdog(self._gpio, 200)
        await asyncio.sleep(0.2)

    async def close(self):
        """
        Stop reading sensor, remove callbacks.
        """
        await self._pi.set_watchdog(self._gpio, 0)
        if self._either_edge_cb:
            self._either_edge_cb.cancel()
            self._either_edge_cb = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def __aiter__(self):
        """
        Support the iterator protocol.
        """
        return self

    async def __anext__(self):
        """
        Call the read method and return temperature and humidity informations.
        """
        await asyncio.sleep(1)
        await self.read()
        return DHT11Result(error_code=self._error,
                           temperature=self.temperature,
                           humidity=self.humidity)


async def main(max_count=1):
    address = ('192.168.1.6', 8888)
    gpio = 4
    count = 0

    async with apigpio.Pi(address) as pi:
        async with DHT11(pi, gpio) as sensor:
            async for result in sensor:
                if result.is_valid():
                    print(result)
                    count += 1

                if count >= max_count:
                    break


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
