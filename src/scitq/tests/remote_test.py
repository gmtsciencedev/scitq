from scitq.workflow import Workflow
from scitq.remote import remote

@remote
def say_hello(who='world'):
    print(f'Hello {who}!')

def launch():
    wf = Workflow('test_remote', debug=True, max_step_workers=1, flavor='local')
    wf.step('hello', command=say_hello, args={'who':'scitq'}, concurrency=1)
    wf.run()

if __name__=='__main__':
    launch()