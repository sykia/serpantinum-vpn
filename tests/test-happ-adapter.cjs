// Synthetic ELF/database fixture: no real subscription or Happ process is used.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'happ-adapter-test-'));
try {
    const binary = Buffer.alloc(1040);
    Buffer.from('7f454c460201', 'hex').copy(binary);
    binary.writeUInt16LE(62, 18);
    binary.writeBigUInt64LE(64n, 32);
    binary.writeUInt16LE(56, 54);
    binary.writeUInt16LE(2, 56);
    function segment(index, file, virtual, length) {
        const p = 64 + index * 56;
        binary.writeUInt32LE(1, p);
        binary.writeBigUInt64LE(BigInt(file), p + 8);
        binary.writeBigUInt64LE(BigInt(virtual), p + 16);
        binary.writeBigUInt64LE(BigInt(length), p + 32);
    }
    segment(0, 512, 0x19e9a0, 0x119);
    segment(1, 1024, 0x714ff0, 16);
    const key = Buffer.from(Array.from({length: 16}, (_, i) => i));
    for (let i = 0; i < 16; i++) {
        Buffer.from([0x83, 0xf0, 1]).copy(binary, 512 + i * 3);
        binary[1024 + i] = key[i] ^ 1;
    }
    const elf = path.join(temporary, 'Happ'); fs.writeFileSync(elf, binary);
    const decoder = path.join(__dirname, '../overlay/scripts/happ-read.cjs');
    const fixture = {order: [1], map: {'1': {name: 'Example provider', privateToken: 'SECRET_SUBSCRIPTION_TOKEN',
        serverOrder: [2], serverMap: {'2': {guid: 'example-guid', name: 'Germany', host: 'example.com', port: 443,
        password: 'SECRET_SERVER_PASSWORD'}}}}};
    const cipher = crypto.createCipheriv('aes-128-gcm', key, Buffer.from('kkkkkkkkkkkk'));
    const encrypted = Buffer.concat([cipher.update(JSON.stringify(fixture)), cipher.final()]);
    const input = {data: encrypted.toString('base64'), tag: cipher.getAuthTag().toString('base64')};
    const result = spawnSync(process.execPath, [decoder, elf], {input: JSON.stringify(input), encoding: 'utf8'});
    assert.equal(result.status, 0, result.stderr);
    const rows = JSON.parse(result.stdout);
    assert.equal(rows.length, 1); assert.equal(rows[0].name, 'Germany');
    assert.equal(rows[0].host, 'example.com');
    assert.equal(result.stdout.includes('SECRET'), false);
    input.tag = Buffer.alloc(16).toString('base64');
    const rejected = spawnSync(process.execPath, [decoder, elf], {input: JSON.stringify(input), encoding: 'utf8'});
    assert.notEqual(rejected.status, 0); assert.equal(rejected.stdout, '');
    console.log('Adapter: metadata-only output and invalid-tag rejection passed');
} finally {
    fs.rmSync(temporary, {recursive: true, force: true});
}
