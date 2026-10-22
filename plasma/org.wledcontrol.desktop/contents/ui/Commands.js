.pragma library

function quote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'";
}

function enqueue(queue, args) {
    if (args[0] === "brightness" && queue.length && queue[queue.length - 1][0] === "brightness")
        queue[queue.length - 1] = args;
    else
        queue.push(args);
}
