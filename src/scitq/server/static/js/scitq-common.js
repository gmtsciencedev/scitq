var function_is_running=false;
var running_time = 0;
async function check_online(func) {
    if (!pause_loop && !function_is_running && !document.hidden) {
        $.getJSON('/ui/ping', async function() {
            const begin_date = Date.now();
            console.log('fetching...');
            function_is_running = true;
            await func();
            running_time = Date.now() - begin_date;
            console.log(`done in ${running_time}ms`);
            function_is_running = false;
        });
    }
}

var pause_loop = false;
async function loop_if_online(func, wait) {
    await func();
    check_online(func, wait);
    var interv = await async function(w){
        return async function(){
            if (running_time>w) {
                w=Math.min(running_time,10*w);
            } else if (w>wait) {
                w=Math.max(wait, w-1000);
            }
            console.log(`waiting ${w}ms`)
            setTimeout(interv, w);
            if (!pause_loop && !document.hidden) {
                await check_online(func);
            }
            };
    }(wait);

    setTimeout(interv, wait);
}


function pause() { 
    if (!pause_loop) {
        pause_loop = true;
        return true;
    } else {return false;} ;
}
  
function unpause() {
    if (pause_loop) {
        pause_loop = false;
        return true;
    } else 
    {return false;}
}

function pause_page() {
    if (!pause_loop) {
        pause_loop = true;
        document.getElementById('pause').innerHTML='Resume';
    } else {
        pause_loop = false;
        document.getElementById('pause').innerHTML='Pause';
    }
}

function remove_from_array(arr, value){
    for( var i = 0; i < arr.length; i++) { 
        if ( arr[i] === value) { 
            arr.splice(i, 1); 
        }
    }
}

function capitalize(string) {
    return string.charAt(0).toUpperCase() + string.slice(1);
}

function display_date(this_date) {
    if (this_date==null) {
        return '';
    }
    else {
        this_date=new Date(this_date + '+00');
        return this_date.toLocaleString();
    }
}

const svg_resume = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-play-circle-fill" 
                    viewBox="0 0 16 16">
                <path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0zM6.79 5.093A.5.5 0 0 0 6 5.5v5a.5.5 0 0 0 .79.407l3.5-2.5a.5.5 0 0 0 0-.814l-3.5-2.5z"/>
            </svg>`;

const svg_pause = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-pause-circle-fill" 
                    viewBox="0 0 16 16">
                <path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0zM6.25 5C5.56 5 5 5.56 5 6.25v3.5a1.25 1.25 0 1 0 2.5 0v-3.5C7.5 5.56 6.94 5 6.25 5zm3.5 0c-.69 0-1.25.56-1.25 1.25v3.5a1.25 1.25 0 1 0 2.5 0v-3.5C11 5.56 10.44 5 9.75 5z"/>
            </svg>`;

const svg_stop = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-x-circle" 
                    viewBox="0 0 16 16">
                <path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14zm0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16z"/>
                <path d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L8 8.707l-2.646 2.647a.5.5 0 0 1-.708-.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708z"/>
            </svg>`;

const svg_break = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-exclamation-lg" 
                    viewBox="0 0 16 16">
                <path d="M7.005 3.1a1 1 0 1 1 1.99 0l-.388 6.35a.61.61 0 0 1-1.214 0L7.005 3.1ZM7 12a1 1 0 1 1 2 0 1 1 0 0 1-2 0Z"/>
            </svg>`;

const svg_restart = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-bootstrap-reboot" 
                    viewBox="0 0 16 16">
                <path d="M1.161 8a6.84 6.84 0 1 0 6.842-6.84.58.58 0 1 1 0-1.16 8 8 0 1 1-6.556 3.412l-.663-.577a.58.58 0 0 1 .227-.997l2.52-.69a.58.58 0 0 1 .728.633l-.332 2.592a.58.58 0 0 1-.956.364l-.643-.56A6.812 6.812 0 0 0 1.16 8z"/>
                <path d="M6.641 11.671V8.843h1.57l1.498 2.828h1.314L9.377 8.665c.897-.3 1.427-1.106 1.427-2.1 0-1.37-.943-2.246-2.456-2.246H5.5v7.352h1.141zm0-3.75V5.277h1.57c.881 0 1.416.499 1.416 1.32 0 .84-.504 1.324-1.386 1.324h-1.6z"/>
            </svg>`;

const svg_download = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-download" 
                    viewBox="0 0 16 16">
                <path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5z"/>
                <path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708l3 3z"/>
            </svg>`;



const svg_delete = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-eraser" 
                    viewBox="0 0 16 16">
                <path d="M8.086 2.207a2 2 0 0 1 2.828 0l3.879 3.879a2 2 0 0 1 0 2.828l-5.5 5.5A2 2 0 0 1 7.879 15H5.12a2 2 0 0 1-1.414-.586l-2.5-2.5a2 2 0 0 1 0-2.828l6.879-6.879zm2.121.707a1 1 0 0 0-1.414 0L4.16 7.547l5.293 5.293 4.633-4.633a1 1 0 0 0 0-1.414l-3.879-3.879zM8.746 13.547 3.453 8.254 1.914 9.793a1 1 0 0 0 0 1.414l2.5 2.5a1 1 0 0 0 .707.293H7.88a1 1 0 0 0 .707-.293l.16-.16z"/>
            </svg>`;

const chevron_up = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-chevron-up" viewBox="0 0 16 16">
            <path fill-rule="evenodd" d="M7.646 4.646a.5.5 0 0 1 .708 0l6 6a.5.5 0 0 1-.708.708L8 5.707l-5.646 5.647a.5.5 0 0 1-.708-.708l6-6z"/>
    </svg>`;
const chevron_down = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-chevron-down" viewBox="0 0 16 16">
            <path fill-rule="evenodd" d="M1.646 4.646a.5.5 0 0 1 .708 0L8 10.293l5.646-5.647a.5.5 0 0 1 .708.708l-6 6a.5.5 0 0 1-.708 0l-6-6a.5.5 0 0 1 0-.708z"/>
    </svg>`;

const svg_trash = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-trash3-fill" 
                        viewBox="0 0 16 16">
            <path d="M11 1.5v1h3.5a.5.5 0 0 1 0 1h-.538l-.853 10.66A2 2 0 0 1 11.115 16h-6.23a2 2 0 0 1-1.994-1.84L2.038 3.5H1.5a.5.5 0 0 1 0-1H5v-1A1.5 1.5 0 0 1 6.5 0h3A1.5 1.5 0 0 1 11 1.5Zm-5 0v1h4v-1a.5.5 0 0 0-.5-.5h-3a.5.5 0 0 0-.5.5ZM4.5 5.029l.5 8.5a.5.5 0 1 0 .998-.06l-.5-8.5a.5.5 0 1 0-.998.06Zm6.53-.528a.5.5 0 0 0-.528.47l-.5 8.5a.5.5 0 0 0 .998.058l.5-8.5a.5.5 0 0 0-.47-.528ZM8 4.5a.5.5 0 0 0-.5.5v8.5a.5.5 0 0 0 1 0V5a.5.5 0 0 0-.5-.5Z"/>
    </svg>`;

const svg_edit = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-pencil-square" viewBox="0 0 16 16">
        <path d="M15.502 1.94a.5.5 0 0 1 0 .706L14.459 3.69l-2-2L13.502.646a.5.5 0 0 1 .707 0l1.293 1.293zm-1.75 2.456-2-2L4.939 9.21a.5.5 0 0 0-.121.196l-.805 2.414a.25.25 0 0 0 .316.316l2.414-.805a.5.5 0 0 0 .196-.12l6.813-6.814z"/><path fill-rule="evenodd" d="M1 13.5A1.5 1.5 0 0 0 2.5 15h11a1.5 1.5 0 0 0 1.5-1.5v-6a.5.5 0 0 0-1 0v6a.5.5 0 0 1-.5.5h-11a.5.5 0 0 1-.5-.5v-11a.5.5 0 0 1 .5-.5H9a.5.5 0 0 0 0-1H2.5A1.5 1.5 0 0 0 1 2.5v11z"/>`;

const svg_wipe = `<svg width="16" height="16" enable-background="new 0 0 1000 1000" version="1.1" viewBox="0 0 16 16" xml:space="preserve" xmlns="http://www.w3.org/2000/svg">
        <g transform="matrix(.015775 0 0 .015775 .84754 .30168)">
            <path d="m599 755.5c-5.6 22.3-34.1 71.1-79.5 136.9 12.4 2.9 24.3 6.1 36.4 8.3 22 4 44.1 7.1 66.1 11.1 7.2 1.3 10.9-1.3 14.7-7 44.2-65.8 79.9-136.1 109.8-209.3 11.7-28.7 21.7-58 32.5-87 1.1-3 2.2-5.9 3.5-9.4 23.7 8.2 46.9 16.2 71.1 24.5-4.3 12.7-8.3 24.8-12.6 36.7-36.4 101.1-81.7 197.8-142.1 287-5 7.4-10.7 14.4-15.6 21.8-11.4 17.1-27.3 22.4-47.2 20.5-76.8-7.3-151.3-24.8-223.4-51.9-131.2-49.4-244.2-125-333.7-234-10.7-13.1-13.8-27.5-6.8-42.9 6.8-14.8 19.7-21.5 35.6-21.7 68.2-0.9 133.9-14.6 197.5-38.6 57.5-21.7 109.9-51.9 150.3-99.5 11.7-13.8 21.2-29.4 32.3-45 20.8 11.7 42.2 23.8 65.7 37-12.2 17.6-23 35.3-35.8 51.4-31.2 39.5-70.6 69.4-114.2 93.7-65.8 36.6-136.9 57.7-210.9 69.7-1.5 0.2-2.9 0.5-6.5 1.2 10.6 9.7 19.5 18.8 29.3 26.7 18.4 14.9 37.1 29.4 56.2 43.4 3.7 2.7 10.2 3.9 14.8 2.9 38-8.6 72.8-23.8 102-50.8-2.5 13.3-26.5 47-60.2 84.6 21.2 10.5 42.5 19.8 62.5 31.5 25.8 15.2 50.5 11 75.8 0.1 42.8-18.5 79.5-46.1 114.6-76.2 5.6-4.8 11.1-9.8 17.8-15.7zm277.3-195.1c-120.1-53.4-239.3-106.5-359.4-159.9 9.9-23.1 25.5-40.6 46.6-53 35.2-20.7 72-23.1 109.3-6.8 48 20.9 96 42 143.5 64 55.8 25.9 82.1 84 65.1 141.7-1.4 4.5-3.2 8.8-5.1 14zm-53.3-209.3c-37.8-16.8-75.2-33.5-112.5-50.1-0.8-0.4-1.3-1.2-2.4-2.2 1.4-2.8 2.7-5.7 4.2-8.4 46.8-87.7 93.5-175.3 140.3-263 7.8-14.7 16.9-19.1 33.8-16.6 15.5 2.3 28.6 8.9 38.7 21 6.6 8 8.3 16.7 4.6 26.8-34.9 96-69.6 192.2-104.4 288.2-0.5 1-1.2 2.1-2.3 4.3z"/>
        </g>
    </svg>`;