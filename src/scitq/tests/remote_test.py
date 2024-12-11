from scitq.workflow import Workflow
from scitq.remote import remote,resource,command

@remote
def say_hello(who='world'):
    print(f'Hello {who}!')

def launch():
    wf = Workflow('test_remote', debug=True, max_step_workers=1, flavor='local')
    wf.step('hello', command=command(say_hello,who='scitq',container=False), resource=resource(), concurrency=1, shell=True)
    wf.run()

if __name__=='__main__':
    launch()