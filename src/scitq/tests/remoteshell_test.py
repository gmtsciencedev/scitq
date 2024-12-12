from scitq.workflow import Workflow,shell_code


def launch():
    wf = Workflow('test_shell', debug=True, max_step_workers=1, flavor='local')
    mycode = shell_code('''
echo 'one
two
three'
''')
    wf.step('multiline shell', command=mycode.command(), resource=mycode.resource(), concurrency=1, container='alpine:latest')
    wf.run()

if __name__=='__main__':
    launch()