from scitq.workflow import Workflow,shell_code


def launch():
    wf = Workflow('test_shell', debug=True, max_step_workers=1, flavor='local')
    wf.step('multiline shell', command=shell_code('''
echo 'one
two
three'
'''), concurrency=1)
    wf.step('multiline shell', command=shell_code('''
echo 'one
two
three'
'''), concurrency=1, container='alpine:latest')
    wf.run()

if __name__=='__main__':
    launch()