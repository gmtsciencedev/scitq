# troubleshooting

## Ansible

`error for nodeX: PLAY [Launch a compute instance] *********************************************** TASK [Gathering Facts] ********************************************************* ok: [localhost] TASK [Launch a VM] ************************************************************* fatal: [localhost]: FAILED! => {"changed": false, "extra_data": {"data": null, "details": "Invalid key_name provided.", "response": "{\"badRequest\": {\"code\": 400, \"message\": \"Invalid key_name provided.\"}}"}, "msg": "BadRequestException: 400: Client Error for url: https://compute.gra11.cloud.ovh.net/v2.1/XXXXXXXXXXXXXXXXXXXXXXX/servers, Invalid key_name provided."} PLAY RECAP ********************************************************************* localhost : ok=1 changed=0 unreachable=0 failed=1 skipped=0 rescued=0 ignored=0 `
:   The `keyname` parameter is wrong: either your forgot to change it in `/etc/ansible/inventory/common` or you forgot to deploy it on your provider console. Or maybe you deployed it but not on this region or not with this name.

`error for nodeX: PLAY [Launch a compute instance] *********************************************** TASK [Gathering Facts] ********************************************************* ok: [localhost] TASK [Launch a VM] ************************************************************* fatal: [localhost]: FAILED! => {"changed": false, "msg": "The instance is available but not Active state: ERROR"} PLAY RECAP ********************************************************************* localhost : ok=1 changed=0 unreachable=0 failed=1 skipped=0 rescued=0 ignored=0 `
:   An internal error of OpenStack, most likely an error of OVH when this reference is no more available in that region. OVH support confirms that you will not be charged for instances that are not available (stuck in ERROR or BUILD status). Simply delete the worker using the [GUI worker view](gui.md#worker-screen-httpui) delete icon and try another region. 

!!! note
    You might want to open OVH console as it will show the ERROR status of the instances quicker than waiting for PYTQ to display the error (that is because Ansible code is slow for this), but please do not use the OVH console to delete instances created with PYTQ: you can delete a server anytime with PYTQ, the code is very safe and will properly delete the objects and any modification Ansible has already done to your manager servers. When the line on the screen is gone, it means the Ansible delete worker procedure went fine and you can trust it was really deleted at provider level. However when you deal with a touchy reference (like the very good but rare i1-180), having the OVH console opened up to quickly know if you are in error or not is really nice. You can also call the support, they keep telling me I should call them to know how many instances of a certain type are available per region, but then I am terribly lazy...

`error for nodeX: PLAY [Launch a compute instance] *********************************************** TASK [Gathering Facts] ********************************************************* ok: [localhost] TASK [Add host and host related variables] ************************************* changed: [localhost] TASK [Launch a VM] ************************************************************* fatal: [localhost]: FAILED! => {"changed": false, "extra_data": {"data": null, "details": "None", "response": "None"}, "msg": "Timeout waiting for the server to come up."} PLAY RECAP ********************************************************************* localhost : ok=2 changed=1 unreachable=0 failed=1 skipped=0 rescued=0 ignored=0 `
:   This error occurs generally when you delete a worker before it had the chance to try three times to be deployed. You can ignore it safely if you deleted such a worker.

## PYTQ task output

`You cannot attach to a stopped container, start it first`
:   This error occurs when a docker accept to start (the binary called was found and could be launched) but fails immediately after (a fraction second before python attach the docker process to a collecting thread). That is hopefully quite rare: look into the worker logs with `journalctl -u pytq-worker`, find the faulty docker launch, and launch it manually in the worker replacing -d option (detach) by -it (interactive), this will show the error.


## Specific cases

### Big outputs
Some programs (notably CAMISIM) are very verbose and generate huge output, so that maybe it is a good idea to redirect the output to a file and rely only on stderr to follow the tasks. If you really need to follow the output during execution, that is however not an option. There are two things you should take care of:

PYTQ will consume large amount of memory in the case, so be certain to have a significant amount of memory available. At least set up some swap, for instance like this:
```bash
fallocate -l 8G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
```

NB: You will have to add the following line in `/etc/fstab` to make it permanent (if required):
```fstab
/swapfile       none    swap    sw      0       0
```

Second, when querying the output of tasks, first forget the GUI, it won't be able to do it. Ideally, you have named your task and you know which one you're interested in, in which case go like this:
```bash
pytq-manage -t 600 task output -n mytaskname > mytaskname.output
```
Note the `-t 600` which tells the client library to be very patient (600s) before hitting timeout.

!!! note
    Be aware that REST is poorly adapted to large dataset and a modest 69Mb log (2 million lines, though) ended up as 19Gb REST message eating that amount of memory in pytq-server and at pytq-manage level upon reception. It did work, though, but I was looking at the server with top and added several swap files (as initially the server had only 8Gb memory...), which can be done live if you're in such a corner (the above procedure is extremely quick).

