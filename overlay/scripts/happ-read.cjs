// Read-only adapter for the installed Happ 4.4.8 database format.
// Only server metadata leaves this process; subscription tokens and configs do not.
const fs = require('fs');
const crypto = require('crypto');
if (!process.argv[2]) throw Error('Pass the Happ ELF executable as argument');
const binary = fs.readFileSync(process.argv[2]);
if (binary.subarray(0, 4).toString('hex') !== '7f454c46' || binary[4] !== 2 || binary[5] !== 1 || binary.readUInt16LE(18) !== 62) throw Error('Happ adapter requires Linux x86_64 ELF');
function offset(address) {
    const start = Number(binary.readBigUInt64LE(32));
    const size = binary.readUInt16LE(54), count = binary.readUInt16LE(56);
    for (let i = 0; i < count; i++) {
        const p = start + i * size;
        const file = Number(binary.readBigUInt64LE(p + 8));
        const virtual = Number(binary.readBigUInt64LE(p + 16));
        const length = Number(binary.readBigUInt64LE(p + 32));
        if (binary.readUInt32LE(p) === 1 && address >= virtual && address < virtual + length) return file + address - virtual;
    }
    throw Error('Unsupported Happ binary');
}
const key = Buffer.from(binary.subarray(offset(0x714ff0), offset(0x714ff0) + 16));
const code = binary.subarray(offset(0x19e9a0), offset(0x19eab8));
let position = 0;
for (let i = 0; i < code.length - 2; i++) {
    if (code[i] === 0x83 && code[i + 1] === 0xf0) key[position++] ^= code[i + 2];
}
if (position !== 16) throw Error('Unsupported database key format');
if (process.argv[3] === '--check-binary') {
    process.stdout.write(JSON.stringify({compatible: true, adapter: 'happ-4.4.8-x86_64'}));
    return;
}
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const decrypt = crypto.createDecipheriv('aes-128-gcm', key, Buffer.from('kkkkkkkkkkkk'));
decrypt.setAuthTag(Buffer.from(input.tag, 'base64'));
const database = JSON.parse(Buffer.concat([decrypt.update(Buffer.from(input.data, 'base64')), decrypt.final()]).toString());
const locations = [];
for (const subscriptionId of database.order || Object.keys(database.map)) {
    const subscription = database.map[String(subscriptionId)];
    if (!subscription) continue;
    for (const serverId of subscription.serverOrder || Object.keys(subscription.serverMap)) {
        const server = subscription.serverMap[String(serverId)];
        if (!server) continue;
        locations.push({id: String(serverId), subscriptionId: String(subscriptionId), guid: server.guid,
            name: server.name || 'Без названия', host: server.host || '', port: Number(server.port) || 443,
            subscription: subscription.name || 'Happ'});
    }
}
process.stdout.write(JSON.stringify(locations));
