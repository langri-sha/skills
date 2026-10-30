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
    repository: 'git+https://github.com/langri-sha/skills.git',

    type: 'module',
  },
  claude: {
    settings: {
      attribution: { commit: '', pr: '', sessionUrl: false },
    },
  },
  changesets: {
    config: { privatePackages: { version: true, tag: true } },
  },
  codeowners: {
    '*': '@langri-sha',
  },
  dagger: {},
  editorConfig: {},
  githubTemplates: {},
  husky: {
    'pre-commit': 'pnpm --silent lint-staged',
  },
  lintStaged: {},
  lintSynthesized: {},
  pnpmWorkspace: {
    minimumReleaseAgeExclude: ['@langri-sha/*', ...Project.presetPackages],
  },
  prettier: {},
  renovate: {
    extends: ['github>langri-sha/renovate-config'],
  },
  typeScriptConfig: {},
  worktrunk: {},
})

project.testTask.exec('node --test test/*.test.js')

project.package?.addEngine('pnpm', '>= 11.0.0')
project.package?.addField('packageManager', 'pnpm@12.16.0')
project.package?.addField('private', true)

// `LICENSE` is maintained by hand, so the license is declared here rather
// than through `package.license`, which would synthesize a second file.
project.package?.addField('license', 'MIT')

project.synth()
