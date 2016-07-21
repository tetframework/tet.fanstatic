import fanstatic
import warnings

from fanstatic.core import DummyNeededResources, NeededResources, Resource
from fanstatic.publisher import Publisher
from pyramid.config import Configurator
from pyramid.request import Request


# noinspection PyAbstractClass
class DummyWarningNeededResources(DummyNeededResources):
    def need(self, resource, slots=None):
        warnings.warn("Dummy NeededResources.need is no-op", RuntimeWarning, stacklevel=3)


def filter_settings(settings):
    prefix = 'tet.fanstatic.'
    return {
        k.replace(prefix, '', 1): v
        for k, v in settings.items()
        if k.startswith(prefix)
    }


class TetFanstaticTween:
    def __init__(self, handler, registry):
        self.handler = handler
        self.registry = registry
        self.config = filter_settings(registry.settings)
        self.publisher = Publisher(fanstatic.get_library_registry())
        self.publisher_signature = self.config.get('publisher_signature', 'fanstatic')
        self.use_application_uri = self.config.get('use_application_uri')

        if self.config.get('use_thread_local'):
            self.needed_factory = fanstatic.init_needed
            self.del_needed = fanstatic.del_needed

        else:
            self.needed_factory = NeededResources
            self.del_needed = lambda: None

        self.prefix = '%s/%s/' % (
            self.config.get('base_url', '').rstrip('/'),
            self.publisher_signature)

        injector_name = self.config.pop('injector', 'topbottom')
        injector_factory = fanstatic.registry.InjectorRegistry.instance().get(injector_name)

        self.injector = injector_factory(self.config)

        # override the class with one that gives warnings
        fanstatic.core.DummyNeededResources = DummyWarningNeededResources

    def __call__(self, request):
        # publisher
        if request.path_info.startswith(self.prefix):
            path_info = request.path_info
            script_name = request.script_name

            request.path_info = path_info.replace(self.prefix, '', 1)
            request.script_name += self.prefix
            response = request.get_response(self.publisher)

            # return response if the resource could be found,
            # otherwise go down
            if response.status_int != 404:
                return response

            request.path_info = path_info
            request.script_name = script_name

        # injector
        needed = self.needed_factory(**self.config)
        if self.use_application_uri and not needed.has_base_url():
            needed.set_base_url(request.application_uri.rstrip('/'))

        request.environ[fanstatic.NEEDED] = needed

        try:
            response = self.handler(request)

            c = (response.content_type or '').lower()
            if (c and needed.has_resources()
                and ('/html' in c or '/xhtml' in c)):

                needed.resources()
                result = self.injector(response.body,
                                       needed,
                                       request,
                                       response)
                try:
                    response.text = result
                except TypeError:
                    response.body = result

        finally:
            del request.environ[fanstatic.NEEDED]
            self.del_needed()

        return response


def needed_resources(request: Request) -> NeededResources:
    return request.environ[fanstatic.NEEDED]


def need(request: Request, resource: Resource, slots: dict=None) -> None:
    request.needed_resources.need(resource, slots)


def includeme(config: Configurator):
    config.add_request_method(needed_resources, reify=True)
    config.add_request_method(need)
    config.add_tween('tet.fanstatic.TetFanstaticTween')
