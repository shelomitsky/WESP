const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const file = require('node:path').join(__dirname, '../plasma/org.wledcontrol.desktop/contents/ui/Commands.js');
assert.ok(fs.existsSync(file), 'Command queue is needed to serialize requests');
const api = {};
vm.runInNewContext(fs.readFileSync(file, 'utf8').replace(/^\.pragma library\s*/, ''), api);
if (process.argv[2] === '--quote') {
    console.log(JSON.stringify(JSON.parse(process.argv[3]).map(value => api.quote(value))));
    process.exit(0);
}
let queue = [];
api.enqueue(queue, ['brightness', '10']);
api.enqueue(queue, ['brightness', '20']);
api.enqueue(queue, ['brightness', '240']);
assert.equal(queue.length, 1);
assert.equal(queue[0][1], '240');
api.enqueue(queue, ['power', 'false']);
api.enqueue(queue, ['brightness', '40']);
assert.equal(queue.length, 3, 'brightness must not move across a power command');
console.log('PASS: latest brightness and power ordering; real shell quoting is checked by test_commands.py');
