import { Project } from '@langri-sha/projen-project'

const project = new Project({
  name: 'skills',
  package: {
    bugsUrl: 'https://github.com/langri-sha/skills/issues',
    description:
      'General-purpose agent skills for Claude Code, Codex and other agents',
    entrypoint: '',
    homepage: 'https://github.com/langri-sha/skills#readme',
    licensed: false,
    minNodeVersion: '24.22.1',
    repository: 'langri-sha/skills',

    type: 'module',
    devDeps: ['@langri-sha/prettier@0.4.11'],
  },
  codeowners: {
    '*': '@langri-sha',
  },
  lintSynthesized: {},
  pnpmWorkspace: {},
  prettier: {
    // Work in flight in these skills is formatted once it lands.
    ignorePatterns: ['/create-session/', '/elate/', '/subdivide/'],
  },
})

project.package?.addEngine('pnpm', '>= 11.0.0')
project.package?.addField('packageManager', 'pnpm@12.15.0')
project.package?.addField('private', true)

// `LICENSE` is maintained by hand, so the license is declared here rather
// than through `package.license`, which would synthesize a second file.
project.package?.addField('license', 'MIT')

project.synth()
