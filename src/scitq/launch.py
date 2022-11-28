#!/usr/bin/env python
import os
from .lib import Server
from .fetch import check_uri
from subprocess import run
import sys
import time
import os

DEFAULT_DOCKER_OPTION = ''
DEFAULT_SERVER = os.environ.get('SCITQ_SERVER','127.0.0.1')

def get_sample(filename):
    """Return last dir of a path"""
    return filename.split('/')[-1]

def check_unique(variable, value, default_value=None):
    "check if an option was not set twice"
    if value!=default_value:
        raise SyntaxError(f'{variable} option was set twice.')


def launch(docker, docker_option, uid, gid, 
            command, server, test, name, batch, input, output, resource):
    """A launching function for scitq tasks
    """

    s=Server(server)

    if docker is not None:
        #command = f'docker run --rm -u {uid}:{gid} {docker_option} {docker} {command}'
        if uid is not None and gid is not None:
            docker_option = f'-u {uid}:{gid} {docker_option}'
        else:
            docker_option = f'{docker_option}'
    elif uid == None and gid == None :
        command = f'{command}'
    else:
        command = f'sudo -u "#{uid}" -g "#{gid}" {command}'
    
    if test:
        print(f'Command that would be sent: {command}')
    else:
        s.task_create(command, name=name, batch=batch, container=docker,
            container_options=docker_option, input=input, output=output,
            resource=resource)

def command_join(command_list):
    """rejoin a shlex.splitted command
    shlex.join should do that but does strange things with some operands (<,>,|)"""
    return " ".join([word if ' ' not in word else (
            '"{}"'.format(word) if "'" in word else "'{}'".format(word) )
        for word in command_list])

def main():
    argv = list(sys.argv[1:])
    docker = None
    uid = None
    gid = None
    server = DEFAULT_SERVER
    docker_option = DEFAULT_DOCKER_OPTION
    test = False
    name = None
    batch = None
    input = ''
    output = None
    resource = ''
    try:
        while True:
            if len(argv)==0 or argv[0] in ['-h','--help']:
                raise SyntaxError('help')
            elif argv[0] in ['-d','--docker']:
                option = argv.pop(0)
                if len(argv)==0:
                    raise SyntaxError(f'{option} requires at least one argument: DOCKERNAME')
                check_unique('docker',docker)
                docker = argv.pop(0)
            elif argv[0] in ['-O','--option']:
                option = argv.pop(0)
                if len(argv)==0:
                    raise SyntaxError(f'{option} requires at least one argument: DOCKEROPTION')
                check_unique('docker_option',docker_option,DEFAULT_DOCKER_OPTION)
                docker_option = argv.pop(0)
            elif argv[0] in ['-u', '--uid']:
                option = argv.pop(0)
                if len(argv)==0:
                    raise SyntaxError(f'{option} requires at least one argument: UID')
                check_unique('uid',uid)
                uid = int(argv.pop(0))
            elif argv[0] in ['-g', '--gid']:
                option = argv.pop(0)
                if len(argv)==0:
                    raise SyntaxError(f'{option} requires at least one argument: GID')
                check_unique('gid',gid)
                gid = int(argv.pop(0))
            elif argv[0] in ['-s', '--server']:
                option = argv.pop(0)
                if len(argv)==0:
                    raise SyntaxError(f'{option} requires at least one argument: scitq server name or IP')
                check_unique('server',server, DEFAULT_SERVER)
                server = argv.pop(0)
            elif argv[0] in ['-t', '--test']:
                option = argv.pop(0)
                test = True  
            elif argv[0] in ['-n', '--name']:
                option = argv.pop(0)
                if len(argv)==0:
                    raise SyntaxError(f'{option} requires at least one argument: NAME, the name of the task')
                check_unique('name',name)
                name = argv.pop(0)
            elif argv[0] in ['-b', '--batch']:
                option = argv.pop(0)
                if len(argv)==0:
                    raise SyntaxError(f'{option} requires at least one argument: BATCH, the batch of this task')
                check_unique('batch',batch)
                batch = argv.pop(0)
            elif argv[0] in ['-i', '--input']:
                option = argv.pop(0)
                if len(argv)==0:
                    raise SyntaxError(f'{option} requires at least one argument: INPUT a quoted space-separated list of file URI')
                if input:
                    input = ' '.join([input,argv.pop(0)])
                else:
                    input = argv.pop(0)
            elif argv[0] in ['-r', '--resource']:
                option = argv.pop(0)
                if len(argv)==0:
                    raise SyntaxError(f'{option} requires at least one argument: INPUT a quoted space-separated list of file URI')
                if resource:
                    resource = ' '.join([resource,argv.pop(0)])
                else:
                    resource = argv.pop(0)
            elif argv[0] in ['-o', '--output']:
                option = argv.pop(0)
                if len(argv)==0:
                    raise SyntaxError(f'{option} requires at least one argument: OUTPUT a unique directory URI')
                check_unique('output',output)
                output = argv.pop(0)
            elif argv[0]=='--':
                argv.pop(0)
                command = command_join(argv)
                break     
            else:
                command = command_join(argv)
                break
        if docker_option != DEFAULT_DOCKER_OPTION and docker is None:
            raise SyntaxError('Do not set Docker options if you do not specify a docker.')
        for category,items in (('input', input.split()), ('resource', resource.split()), ('output', [output])):
            for item in items:
                try:
                    if item is not None:
                        check_uri(item)
                except Exception as e:
                    raise SyntaxError(f'Defect in {category}: {e.args[0]}')
        launch(docker=docker, docker_option=docker_option, uid=uid, gid=gid,
            command=command, server=server, test=test, name=name, batch=batch,
            input=input, output=output, resource=resource)
    except SyntaxError as e:
        if e.args[0]!='help':
            print('Syntax error : {}'.format(e.args[0]), file=sys.stderr)
            sys.exit(2)
        print(f"""Usage:
scitq-launch     [(-h|--help)] [(-d|--docker) DOCKERNAME [(-o|--option) DOCKEROPTION]] 
                [(-u|--uid) UID] [(-g|--gid) GID] [(-s|--server) SERVER] [(-t|--test)] 
                [(-n|--name) NAME] [(-b|--batch) BATCH] [(-i|--input) INPUT] 
                [(-o|--output) OUTPUT] [(-r|--resource) OUTPUT] [--] COMMAND
    Add a task in scitq with :
    -h,--help       display this help message
    -d,--docker     execute the task in a docker container (named DOCKERNAME)
                    default to None - the task is executed natively
    -O,--option     (O is capital o) set docker options to DOCKEROPTION 
                    (default to '{DEFAULT_DOCKER_OPTION}') 
    -u,--uid        execute the task as this UID (with -u in docker or in sudo
                    if docker is not used). Default to current user UID ({uid})
                    BE CAREFUL: if not with docker, the corresponding user must 
                    exist on (remote) system,
    -g,--gid        execute the task as this GID (with -u in docker or -g in 
                    sudo). Default to current user GID ({gid})
                    BE CAREFUL: if not with docker, the corresponding group must 
                    1) exists on (remote) system,
                    2) user with uid UID must be a member of this group;
    -s,--server     send the order to server SERVER (default to {DEFAULT_SERVER})
                    (this default value can be changed using SCITQ_SERVER environment
                    variable)
    -t,--test       print the actual final task sent to the server instead
                    of really sending it (for debug purpose)
    -n,--name       set the name of the command, default to None, no name
    -b,--batch      set the name of the batch, default to None, default batch
    -i,--input      set some INPUT URIs (quoted and space separated) like 
                    s3://.../...fq.gz or ftp:///.../...fq.gz that must be preloaded
                    (in /input directory in docker, or in the directory specified
                    in INPUT environment variable if docker is not used)
                    NB **new** input option can be specified several times
    -o,--output     set OUTPUT, a directory URI in which all output result of the
                    task will be copied (output is simply the content of /output
                    directory in docker, or in the directory specified in OUTPUT
                    environment variable if docker is not used)
    -r,--resource   set some RESOURCE URIs (quoted and space separated) very much
                    like INPUT (see -i) except RESOURCEs are only downloaded once
                    per worker and shared between tasks (in /resource directory 
                    in docker or in the directory specified in RESOURCE environment
                    variable if docker is not used). It should be specified for 
                    all the tasks that need it but it will only be downloaded once
                    per host (provided the RESOURCE is specified exactly in the 
                    same way for each task). 
                    NB a RESOURCE URI may end with '|gunzip' in which case it
                    will be unzipped (with pigz) upon reception.
                    NB2 resource option can be specified several times
    --              the last argument, COMMAND, may be constituted of several
                    words. Usually this list of words starts with a non-dashed 
                    word like sh or bash, in which case there is no possible 
                    ambiguity. But in some case, the command may start with a 
                    dash in which case it may overlap with one the above option:
                    to avoid that, specifying -- will make sure the next word, 
                    whatever it is, is interpreted as the beginning of the 
                    command. 
    
    COMMAND is a usual shell command

    Be careful that if you do not define INPUT/OUTPUT and use docker (-d) then 
    all data transfer is manually done within your task. /data is generally used
    in that case, it is mounted in worker if an nfs_server variable is defined
    in ansible (for manager group, see /etc/ansible/inventory/common) - and NFS
    is minimally set up on that server. 
""")
        sys.exit(2)



if __name__=="__main__":
    main()
