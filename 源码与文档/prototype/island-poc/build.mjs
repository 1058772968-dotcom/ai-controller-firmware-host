import { build } from 'esbuild';
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const base = new URL('./', import.meta.url);
const bundle = await build({ entryPoints: [fileURLToPath(new URL('main.js', base))], bundle: true, write: false, minify: true, format: 'iife', target: ['es2022'], legalComments: 'inline' });
const [html, css] = await Promise.all([readFile(new URL('template.html', base), 'utf8'), readFile(new URL('style.css', base), 'utf8')]);
const output = html.replace('/*__STYLE__*/', () => css).replace('/*__SCRIPT__*/', () => bundle.outputFiles[0].text.replaceAll('</script', '<\\/script'));
const file = new URL('../AI键盘-灵动岛POC演示.html', base);
await writeFile(file, output);
console.log('Built ' + fileURLToPath(file));

// --artifact <路径>：另出一份在线发布版。发布时外层会自动包上 doctype/head/body，这里去掉自带的骨架标签，
// 并标记为托管环境（受限框架里 WebHID 不可用，「连接 AI KEY」改为提示本机启动）。
const ai = process.argv.indexOf('--artifact');
if (ai > 0 && process.argv[ai + 1]) {
  const hosted = output
    .replace(/<!doctype html>\s*/i, '').replace(/<html[^>]*>\s*/i, '').replace(/<\/html>\s*$/i, '')
    .replace(/<\/?head>\s*/gi, '').replace(/<body[^>]*>/i, '').replace(/<\/body>\s*/i, '')
    .replace(/<meta charset[^>]*>\s*/i, '').replace(/<meta name="viewport"[^>]*>\s*/i, '')
    .replace(':root{', ':root{color-scheme:dark;')
    .replace('<script>', () => '<script>window.__ISLAND_HOSTED=true;</script>\n<script>');
  await writeFile(process.argv[ai + 1], hosted);
  console.log('Built (artifact) ' + process.argv[ai + 1]);
}
