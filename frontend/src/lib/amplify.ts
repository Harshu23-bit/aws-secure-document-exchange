import { Amplify } from 'aws-amplify'

const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID
const userPoolClientId = import.meta.env.VITE_COGNITO_CLIENT_ID
const cognitoDomain = import.meta.env.VITE_COGNITO_DOMAIN

export const amplifyConfigured = Boolean(
  userPoolId && userPoolClientId && cognitoDomain,
)

if (amplifyConfigured) {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId,
        userPoolClientId,
        loginWith: {
          oauth: {
            domain: cognitoDomain,
            scopes: ['openid', 'email', 'cloudsec-api/access'],
            redirectSignIn: [
              `${window.location.origin}/auth/callback`,
            ],
            redirectSignOut: [
              `${window.location.origin}/`,
            ],
            responseType: 'code',
          },
        },
      },
    },
  })
}
