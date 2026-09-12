/**
 * Obsolete: rendered the old Subject → Topic → Note hierarchy tree against
 * `GET /api/v1/hierarchy/outline`, which the NexaNota redesign removed (that
 * endpoint is no longer mounted - see backend/app/api/v1/router.py).
 * Replaced by `GraphPanel.tsx`, which App.tsx now renders instead.
 *
 * Nothing imports this file any more. It is left as an empty module rather
 * than deleted outright only because the file bridge to this machine could
 * not run a delete command when this cleanup was done - safe to delete this
 * file whenever convenient.
 */

export {};
