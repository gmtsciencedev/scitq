# troubleshooting

## Ansible

`error for nodeX: PLAY [Launch a compute instance] *********************************************** TASK [Gathering Facts] ********************************************************* ok: [localhost] TASK [Launch a VM] ************************************************************* fatal: [localhost]: FAILED! => {"changed": false, "extra_data": {"data": null, "details": "Invalid key_name provided.", "response": "{\"badRequest\": {\"code\": 400, \"message\": \"Invalid key_name provided.\"}}"}, "msg": "BadRequestException: 400: Client Error for url: https://compute.gra11.cloud.ovh.net/v2.1/XXXXXXXXXXXXXXXXXXXXXXX/servers, Invalid key_name provided."} PLAY RECAP ********************************************************************* localhost : ok=1 changed=0 unreachable=0 failed=1 skipped=0 rescued=0 ignored=0 `
:   The `keyname` parameter is wrong: either your forgot to change it in `/etc/ansible/inventory/common` or you forgot to deploy it on your provider console. Or maybe you deployed it but not on this region or not with this name.

`error for nodeX: PLAY [Launch a compute instance] *********************************************** TASK [Gathering Facts] ********************************************************* ok: [localhost] TASK [Launch a VM] ************************************************************* fatal: [localhost]: FAILED! => {"changed": false, "msg": "The instance is available but not Active state: ERROR"} PLAY RECAP ********************************************************************* localhost : ok=1 changed=0 unreachable=0 failed=1 skipped=0 rescued=0 ignored=0 `
:   An internal error of OpenStack, most likely an error of OVH when this reference is no more available in that region. The only way to solve this is to delete the worker in PYTQ. 

`error for nodeX: Instance '' has been deleted, or its row is otherwise not present.`
:   This error occurs generally when you delete a worker before it had the chance to try three times to be deployed. You can ignore it safely if you deleted such a worker.