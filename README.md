# ansible-tesla-module
What

This is an ansible module for your Tesla. You can use it to pop the trunk from the command line, or since it is ansible, pop the trunk 20 times on a 1000 Tesla's at the same time.

How to use

Pass in environment variables with your email/password you use with your Tesla app. Pass in VIN info if you have more than one Tesla. See test.yaml for examples

The available functions are:

```
actuate_frunk
actuate_trunk 
disable_sentry_mode
enable_sentry_mode 
flash_lights 
get_charge_state
get_climate_state 
get_drive_state 
get_gui_settings
get_nearby_charging 
get_odometer 
get_service_data
get_vehicle_data 
get_vehicle_legacy_data
get_vehicle_online_state 
get_vehicle_state
get_vehicle_summary 
is_car_locked
is_sentry_mode_enabled 
is_vehicle_online 
list_vehicles
set_charge_limit 
set_sentry_mode 
streaming_ping
toggle_sentry_mode 
wake_up_vehicle
```

Why

I really don't know.  I recently implemented the Tesla USB project to fake a USB drive from a raspberry pi zero ( https://www.youtube.com/watch?v=ETs6r1vKTO8 ), and created some ansible playbooks to control it. On this device, it has a python file `tesla_api.py`. It uses the Tesla API to keep the car awake so it can finish archiving files, if you don't have sentry mode enabled the car normally turns the power to the USB port off. I searched if Tesla had one available, and while I found they use ansible in their GitHub repo, there was not module.

Last night I had a bottle of Maker's Mark and I decided to turn it into an Ansible Module. I had a dream I could activate summon and send the car to the store, a worker would place food inside, and I can summon it back home. I made a neighborhood business with it. I made an app. I would watch my Ansible Tower recieve an API request that food was ready to be picked up, see my car wake up and head to the store, and I would see money deposited in my bank account.  I woke up this morning and found it mostly worked. I haven't touched Summon yet, but if you can do it with a mobile phone, I can do it via command line.  I don't have the FSD Beta with neighborhood driving yet, so I can't test it anyway.

How

I took the `tesla_api.py` and shoved it into an example ansible module, https://github.com/cytopia/ansible-modules .  From the looks of it, everything can be converted to ansible uri calls in a set of playbooks, but the python script had enough bare python level http calls that I figured it would suffice to just create a wrapper.  All I really had to do was change the 'print' statements to a dict containing success/failure, whether it was skipped, and a msg to return to the calling python funtion. Another change was converting all the 'sys.exit' calls to return a dict object.



What's next?

Nothing, I guess. Maybe integrate with the Linux Control project ( https://www.youtube.com/watch?v=luBkZoSbxm4&feature=youtu.be ) to honk my horn and open the doors with 'hey google, dude where's my car?'  I was thinking about going into CAN bus hacking to see if I can use a pro drone radio remote control to drive my car like a toy. https://www.youtube.com/watch?v=54jQ7ut3FBA

License

It's yours to break your $100,000 electric toy car, and you can't blame me.
