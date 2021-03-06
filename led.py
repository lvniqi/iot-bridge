#!/usr/bin/python3
import socket
import asyncio
import time
import json

import urllib
import urllib.request
import urllib.parse

#%% controller
class naive_controller(object):
    #ison = is on now
    def __init__(self, freeze_timeout=15, ison=False):
        self._ison = ison
        self._freeze_timeout = freeze_timeout
        self._last_on_time = time.time()
        self._type = 'controller'

    @property
    def ison(self):
        """Return true if switch is on."""
        return self._ison

    def on(self, **kwargs):
        """Turn the switch on."""
        raise NotImplementedError("method on is not implemented.")

    def off(self, **kwargs):
        """Turn the switch off."""
        raise NotImplementedError("method off is not implemented.")

    def check_timeout(self):
        return time.time() - self._last_on_time > self._freeze_timeout


class tasmota_controller(naive_controller):
    #ison = is on now
    def __init__(self, host, freeze_timeout=15, ison=False):
        self._host = host
        super().__init__(freeze_timeout=freeze_timeout, ison=ison)

    def on(self, **kwargs):
        """Turn the switch on."""
        if not self._ison:
            try:
                url = f"http://{self._host}/cm?cmnd=Power%20On"
                f = urllib.request.urlopen(url)
                print(f.read().decode('utf-8'))
                self._ison = True
            except Exception as e:
                print(e)
        self._last_on_time = time.time()

    def off(self, **kwargs):
        """Turn the switch off."""
        force_state = kwargs.get('force_state', False)
        is_force = kwargs.get('is_force', False)
        last_remote_time = kwargs.get('last_remote_time', -1)
        if (self._ison and self.check_timeout()) or is_force:
            try:
                url = f"http://{self._host}/cm?cmnd=Power%20Off"
                f = urllib.request.urlopen(url)
                print(f.read().decode('utf-8'))
                self._ison = False
            except Exception as e:
                print(e)


class udp_local_controller(naive_controller):
    #ison = is on now
    def __init__(self,
                 host,
                 port,
                 freeze_timeout=15,
                 ison=False,
                 on_msg='door close',
                 off_msg='door open'):
        self._host = host
        self._port = port
        self._on_msg = on_msg.encode('utf-8') if type(on_msg) == str else on_msg
        self._off_msg = off_msg.encode('utf-8') if type(off_msg) == str else off_msg
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        super().__init__(freeze_timeout=freeze_timeout, ison=ison)

    def __del__(self):
        self._sock.close()

    def on(self, **kwargs):
        force_state = kwargs.get('force_state', True)
        if force_state:
            self._sock.sendto(self._on_msg, (self._host, self._port))
        else:
            self.off(**kwargs)

    def off(self, **kwargs):
        self._sock.sendto(self._off_msg, (self._host, self._port))

#%% remote
class naive_remote(object):
    def __init__(self, remote_freeze_timeout=600):
        self._remote_freeze_timeout = remote_freeze_timeout
        self._time = None
        self.update_time()
        self._type = 'remote'
        self._force_state = False
        self._last_remote_time = -self._remote_freeze_timeout

    def login(self):
        raise NotImplementedError("method login is not implemented.")

    def update_time(self):
        self._time = time.time()

    def run_one_step(self):
        raise NotImplementedError("method run_one_step is not implemented.")

    def remote_on(self, **kwargs):
        raise NotImplementedError("method remote_on is not implemented")

    def remote_off(self, **kwargs):
        raise NotImplementedError("method remote_off is not implemented.")

    @property
    def enable_off(self):
        if self.force_state and time.time() - self._last_remote_time < self._remote_freeze_timeout:
            return False
        return True

    @property
    def last_remote_time(self):
        return self._last_remote_time
    @property
    def force_state(self):
        return self._force_state


class bigiot_remote(naive_remote):
    def __init__(self, api_key, device_id, remote_freeze_timeout=600):
        super().__init__(remote_freeze_timeout=remote_freeze_timeout)
        self._api_key = api_key
        self._device_id = device_id
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._loop = asyncio.get_event_loop()

    def login(self):
        #connect first
        host = "www.bigiot.net"
        port = 8181
        while True:
            try:
                self._sock.connect((host, port))
                break
            except Exception as e:
                print('waiting for connect bigiot.net...')
                print('error is ', e)
                time.sleep(2)
        #then login
        checkinBytes = bytes(
            '{\"M\":\"checkin\",\"ID\":\"' + self._device_id + '\",\"K\":\"' +
            self._api_key + '\"}\n',
            encoding='utf8')
        self._sock.settimeout(0)
        self._sock.sendall(checkinBytes)

    def _process(self, msg):
        msg = json.loads(msg)
        if msg['M'] == 'say':
            if msg['C'] == 'play':
                self._force_state = True
                self._last_remote_time = time.time()
                self.remote_on()
                #print('on')
            elif msg['C'] == 'stop':
                self._force_state = False
                self._last_remote_time = -self._remote_freeze_timeout
                if time.time(
                ) - self._last_remote_time > self._remote_freeze_timeout:
                    self.remote_off(is_force=True)
                #print('off')
        elif msg['M'] == 'checked':
            pass
        else:
            print(msg)

    def _keep_online(self):
        if time.time() - self._time > 40:
            try:
                self._sock.sendall(b'{\"M\":\"status\"}\n')
            except BrokenPipeError as e:
                print(e)
                print('reinit now')
                self._relogin()
            self.update_time()

    async def _keep_online_run_step(self):
        self._keep_online()

    async def _main_run_step(self):
        try:
            msg = await self._get_message()
            if msg:
                self._process(msg)
        except Exception as e:
            print(e)

    async def _get_message(self):
        data = b''
        d = b''
        retry_count = 3
        for _ in range(1024):
            try:
                d = self._sock.recv(1)
            except BlockingIOError as e:
                retry_count -= 1
                if data == b'' or retry_count == 0:
                    break
                else:
                    await asyncio.sleep(0.005)
            except Exception as e:
                print("get error:", type(e), e)
                retry_count -= 1
                if retry_count == 0:
                    break
                else:
                    await asyncio.sleep(0.005)
            if d != b'\n':
                data += d
            else:
                return str(data, encoding='utf-8')
        return ''

    def run_one_step(self):
        tasks = [
            asyncio.ensure_future(self._main_run_step()),
            asyncio.ensure_future(self._keep_online_run_step()),
        ]

        self._loop.run_until_complete(asyncio.wait(tasks))

    def __del__(self):
        self._loop.close()
        self._sock.close()

    def _relogin(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.login()


class fusion_remote_controller(object):
    def __init__(self, **kwargs):
        self.remote = kwargs['remote']
        self.controller = kwargs['controller']
        self.remote.remote_on = lambda **kwargs: self.controller.on(**kwargs)
        self.remote.remote_off = lambda **kwargs: self.controller.off(**kwargs)
        self.remote.login()

    def on(self, **kwargs):
        kwargs['force_state'] = self.remote.force_state
        kwargs['last_remote_time'] = self.remote.last_remote_time
        self.controller.on(**kwargs)

    def off(self, **kwargs):
        if self.remote.enable_off:
            kwargs['force_state'] = self.remote.force_state
            kwargs['last_remote_time'] = self.remote.last_remote_time
            self.controller.off(**kwargs)

    def run_one_step(self):
        self.remote.run_one_step()

    @property
    def ison(self):
        return self.controller.ison

#%% factory functions
def get_remote(type, **kwargs):
    if type == 'bigiot_remote':
        co_varnames = [
            x for x in bigiot_remote.__init__.__code__.co_varnames
            if x != 'self'
        ]
        kwargs = dict([(k, v) for k, v in kwargs.items() if k in co_varnames])
        return bigiot_remote(**kwargs)
    else:
        raise KeyError("type %s is not find" % str(type))


def get_controller(type, **kwargs):
    if type == 'udp_local_controller':
        co_varnames = [
            x for x in udp_local_controller.__init__.__code__.co_varnames
            if x != 'self'
        ]
        kwargs = dict([(k, v) for k, v in kwargs.items() if k in co_varnames])
        return udp_local_controller(**kwargs)
    elif type == 'tasmota_controller':
        co_varnames = [
            x for x in tasmota_controller.__init__.__code__.co_varnames
            if x != 'self'
        ]
        kwargs = dict([(k, v) for k, v in kwargs.items() if k in co_varnames])
        return tasmota_controller(**kwargs)
    elif type == 'fusion_controller':
        remote = get_remote(kwargs['remote'], **kwargs)
        controller = get_controller(kwargs['controller'], **kwargs)
        return fusion_remote_controller(remote=remote, controller=controller)
    else:
        raise KeyError("type %s is not find" % str(type))


if __name__ == "__main__":
    #must be modified===
    device_id = 'xxx'
    api_key = 'xxxxxxx'
    host = "xxx.xxx.xxx.xxx"
    #modify end=========
    #tasmota_controller_t = get_controller(type='tasmota_controller',host=host)
    #bigiot_remote_t = get_remote(type='bigiot_remote',api_key=api_key, device_id=device_id)

    device = get_controller(
        type='fusion_controller',
        remote='bigiot_remote',
        controller='tasmota_controller',
        api_key=api_key,
        device_id=device_id,
        host=host)

    host = "xxx.xxx.x.xxx"
    port = 55005
    device = get_controller(
        type='fusion_controller',
        remote='bigiot_remote',
        controller='udp_local_controller',
        api_key=api_key,
        device_id=device_id,
        host=host,
        port=port)

    while True:
        device.run_one_step()
    #main_loop_func = asyncio.wait(tasks)
    #main_loop_func.send()
    #loop.close()

    #while True:
    #    time.sleep(1)
