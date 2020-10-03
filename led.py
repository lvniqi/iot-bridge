#!/usr/bin/python3
import socket
import asyncio
import time
import json

import urllib
import urllib.request
import urllib.parse


class naive_controller(object):
    #ison = is on now
    def __init__(self,freeze_timeout=15,ison=False):
        self._ison = ison
        self._freeze_timeout = freeze_timeout
        self._last_on_time = time.time()
    
    @property
    def ison(self):
        """Return true if switch is on."""
        return self._ison


    def on(self, **kwargs):
        """Turn the switch on."""
        if not self._ison:
            self._ison = True
        self._last_on_time = time.time()

    def off(self, **kwargs):
        """Turn the switch off."""
        is_force = kwargs.get('is_force', False)
        if (self._ison and self.check_timeout()) or is_force:
            self._ison = False

    def check_timeout(self):
        return time.time() - self._last_on_time > self._freeze_timeout

    def run_step(self):
        pass
    

class tasmota_controller(naive_controller):
    #ison = is on now
    def __init__(self,host,freeze_timeout=15,ison=False):
        self._host = host
        super().__init__(freeze_timeout=freeze_timeout,ison=ison)

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
        is_force = kwargs.get('is_force', False)
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
    def __init__(self,host,port,freeze_timeout=15,ison=False,on_msg = 'door close', off_msg = 'door open'):
        self._host = host
        self._port = port
        self._on_msg = on_msg
        self._off_msg = off_msg
        self._sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self._sock.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
        super().__init__(freeze_timeout=freeze_timeout,ison=ison)
    

    def __del__(self):
        self._sock.close()


    def on(self, **kwargs):
        self._sock.sendto(self._on_msg,(self._host,self._port))

    def off(self, **kwargs):
        self._sock.sendto(self._off_msg,(self._host,self._port))


class fusion_controller(tasmota_controller):
    def __init__(self, api_key, device_id, host, init_freeze_timeout=15, remote_freeze_timeout=600, ison=False):
        self.api_key = api_key
        self.device_id = device_id
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.time = None
        self.update_time()
        self.loop = asyncio.get_event_loop()
        ##% for remote
        self.remote_freeze_timeout = remote_freeze_timeout
        self.last_remote_time = - self.remote_freeze_timeout
        #% end for remote time
        super().__init__(host,init_freeze_timeout,ison)

    def connect(self):
        host = "www.bigiot.net"
        port = 8181
        while True:
            try:
                self.sock.connect((host, port))
                break
            except:
                print('waiting for connect bigiot.net...')
                time.sleep(2)

    def login(self):
        checkinBytes = bytes(
            '{\"M\":\"checkin\",\"ID\":\"' + self.device_id + '\",\"K\":\"' +
            self.api_key + '\"}\n',
            encoding='utf8')
        self.sock.settimeout(0)
        self.sock.sendall(checkinBytes)

    def process(self, msg):
        msg = json.loads(msg)
        if msg['M'] == 'say':
            if msg['C'] == 'play':
                self.last_remote_time = time.time()
                self.on()
                #print('on')
            elif msg['C'] == 'stop':
                self.last_remote_time =  - self.remote_freeze_timeout
                self.off(is_force=True)
                #print('off')
        elif msg['M'] == 'checked':
            pass
        else:
            print(msg)
        # print(msg)

    def off(self, **kwargs):
        #check if not remote time out
        if time.time() - self.last_remote_time > self.remote_freeze_timeout:
            super().off(**kwargs)



    def keep_online(self):
        if time.time() - self.time > 40:
            try:
                self.sock.sendall(b'{\"M\":\"status\"}\n')
            except BrokenPipeError as e:
                print(e)
                print('reinit now')
                self.re_login()
                
            self.update_time()

    def re_login(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect()
        self.login()

    def update_time(self):
        self.time = time.time()

    async def keep_online_run_async(self):
        while True:
            await self.keep_online_run_step()
            await asyncio.sleep(1)

    async def keep_online_run_step(self):
        self.keep_online()

    def run_one_step(self):
        tasks = [
            asyncio.ensure_future(self.main_run_step()),
            asyncio.ensure_future(self.keep_online_run_step()),
        ]

        self.loop.run_until_complete(asyncio.wait(tasks))

    async def main_run_async(self):
        while True:
            await self.main_run_step()
    
    async def main_run_step(self):
        try:
            msg = await self.get_message()
            if msg:
                self.process(msg)
        except Exception as e:
            print(e)


    async def get_message(self):
        data = b''
        d = b''
        retry_count = 3
        for _ in range(1024):
            try:
                d = self.sock.recv(1)
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

    def __del__(self):
        self.loop.close()


if __name__ == "__main__":
    #must be modified===
    #device_id = 'xxx'
    #api_key = 'xxxxxxx'
    #host = "xxx.xxx.xxx.xxx"
    #modify end=========
    device = fusion_controller(api_key, device_id, host)
    device.connect()
    device.login()

    while True:
        device.run_one_step()
    #main_loop_func = asyncio.wait(tasks)
    #main_loop_func.send()
    #loop.close()

    #while True:
    #    time.sleep(1)
