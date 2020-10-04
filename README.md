# this is a bridge module for tasmota devices to connect with Tmall-Genie by using bigiot service



# usage

1. you should flash your esp8266 / esp32 device with [tasmota firmware](https://github.com/arendst/Tasmota).

2. please register a account in [bigiot](https://www.bigiot.net/) website.

3. after that, you can find a device id and api key in bigiot website.

4. use command as belows:

   ```python
   device = get_controller(
       type='fusion_controller',
       remote='bigiot_remote',
       controller='tasmota_controller',
       api_key=api_key,
       device_id=device_id,
       host=host)
   while True:
       device.run_one_step()
   ```

5. you can connect your tasmota with bigiot now !

6. add bigiot account in Tmall-Genie, then, you can use Tmall-Genie to control tasmota devices.