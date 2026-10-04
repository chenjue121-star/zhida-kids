const { createContextStore } = require('../stores/context');
const { createSession } = require('./session');
const { createApi } = require('./api');
let runtime;
function getRuntime() {
  if (!runtime) {
    const context = createContextStore();
    const session = createSession(wx, context);
    const api=createApi(wx, session, context);
    runtime = { context, session, api,
      plans:require('./plans').createPlans(api,session,context),
      outfits:require('./outfits').createOutfits(api,session,context),
      outfitStore:require('../stores/outfit-context').createOutfitStore(session,context),
      wardrobe:require('./wardrobe').createWardrobe(api,session),
      intake:require('./intake').createIntake(api,session),
      media:require('./media').createMedia(wx,api,session,context) };
  }
  return runtime;
}
module.exports = { getRuntime };
