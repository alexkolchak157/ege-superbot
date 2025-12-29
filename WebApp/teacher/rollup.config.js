import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';

export default {
  input: 'js/main.js',
  output: {
    file: 'bundle.js',
    format: 'iife',
    name: 'TeacherApp',
    sourcemap: true,
    inlineDynamicImports: true
  },
  plugins: [
    resolve(),
    commonjs()
  ]
};
